import { AttributeValue, DynamoDBClient, GetItemCommand } from '@aws-sdk/client-dynamodb'
import { DecryptCommand, KMSClient } from '@aws-sdk/client-kms'
import { LRUCache } from 'lru-cache'
import { setTimeout as sleep } from 'node:timers/promises'
import pLimit from 'p-limit'

const KMS_TIMEOUT_MS = 5000
const DYNAMODB_TIMEOUT_MS = 5000
/** Bounds one lookup with its retries, well inside Kafka's max.poll.interval.ms of 300s, as the v3 read budget does. */
const READ_BUDGET_MS = 30_000
const KMS_CONCURRENCY = 8
/** A tombstone written after this is seen within this time, as the v3 row cache bounds it. */
const CACHE_LIFETIME_MS = 300_000

type Item = Record<string, AttributeValue>

type PendingRead = { result: Promise<TeamMonthKey>; controller: AbortController; waiters: number }

/**
 * The key rows of a month expire at the start of the month this many months later. A session writes up to about 15
 * days after its key month and its objects live up to 98 days, so this leaves a margin to raise the raw window.
 */
const KEY_LIFETIME_MONTHS = 5

/**
 * A team's key for one UTC month. `missing` means no row: the recorder stores the row before it sends a URL, so the row
 * expired or was removed. `deleted` is a tombstone. In both cases the caller stores nothing.
 */
export type TeamMonthKey = { status: 'ok'; key: Buffer } | { status: 'missing' } | { status: 'deleted' }

/** The KMS encryption context of a team month key. The Rust recorder and the key policy use the same one. */
export function teamMonthWrappingContext(teamId: number, keyMonth: string): Record<string, string> {
    return { key_month: keyMonth, purpose: 'ai-research-v4', team_id: String(teamId) }
}

export function teamMonthRowKey(teamId: number, keyMonth: string): Item {
    return { pk: { S: `team:${teamId}` }, sk: { S: `month:${keyMonth}` } }
}

/** The `expires_at` of the key rows of `keyMonth` (`YYYY-MM`), in milliseconds. The Rust recorder writes the same value. */
export function teamMonthKeyExpiresAtMs(keyMonth: string): number {
    const [year, month] = keyMonth.split('-').map(Number)
    return Date.UTC(year, month - 1 + KEY_LIFETIME_MONTHS, 1)
}

/**
 * Reads the v4 team month keys in `ai-research-replay-v4-keys`. Only the recorder writes this table, so this class
 * never stores a key, and the caller drops an image whose team and month have no key.
 */
export class TeamMonthKeys {
    private readonly cache = new LRUCache<string, TeamMonthKey>({ max: 10_000, ttl: CACHE_LIFETIME_MS })
    private readonly pending = new Map<string, PendingRead>()
    private readonly kmsConcurrency = pLimit(KMS_CONCURRENCY)
    private nextKmsRequestAt = 0

    constructor(
        private readonly dynamo: Pick<DynamoDBClient, 'send'>,
        private readonly kms: Pick<KMSClient, 'send'>,
        private readonly tableName: string,
        private readonly kmsKeyArn: string,
        private readonly kmsRequestsPerSecond = 150,
        private readonly readBudgetMs = READ_BUDGET_MS
    ) {
        if (!(kmsRequestsPerSecond > 0)) {
            throw new Error('the v4 KMS request rate must be positive')
        }
    }

    /** `signal` stops this caller's wait. A shared read stops only once every caller that waits on it has stopped. */
    public async get(teamId: number, keyMonth: string, signal?: AbortSignal): Promise<TeamMonthKey> {
        signal?.throwIfAborted()
        const id = `${teamId}:${keyMonth}`
        const cached = this.cache.get(id)
        if (cached) {
            return cached
        }
        // Concurrent requests for one team and month share a read, so a burst of images makes one KMS call.
        let read = this.pending.get(id)
        if (!read) {
            const controller = new AbortController()
            const result = this.resolve(teamId, keyMonth, controller.signal).then((key) => {
                // Only a key row and a tombstone are held, as in the v3 row cache.
                if (key.status !== 'missing') {
                    this.cache.set(id, key)
                }
                return key
            })
            const started: PendingRead = { result, controller, waiters: 0 }
            const forget = (): void => {
                if (this.pending.get(id) === started) {
                    this.pending.delete(id)
                }
            }
            result.then(forget, forget)
            this.pending.set(id, started)
            read = started
        }
        read.waiters += 1
        try {
            return await (signal ? untilAborted(read.result, signal) : read.result)
        } finally {
            read.waiters -= 1
            if (read.waiters === 0 && signal?.aborted) {
                // A later caller must start a new read, not join one that is about to fail.
                if (this.pending.get(id) === read) {
                    this.pending.delete(id)
                }
                read.controller.abort(signal.reason)
            }
        }
    }

    private async resolve(teamId: number, keyMonth: string, abandoned: AbortSignal): Promise<TeamMonthKey> {
        const deadline = AbortSignal.any([AbortSignal.timeout(this.readBudgetMs), abandoned])
        const stored = await this.dynamo.send(
            new GetItemCommand({
                TableName: this.tableName,
                Key: teamMonthRowKey(teamId, keyMonth),
                ConsistentRead: true,
            }),
            { abortSignal: AbortSignal.any([deadline, AbortSignal.timeout(DYNAMODB_TIMEOUT_MS)]) }
        )
        if (!stored.Item) {
            return { status: 'missing' }
        }
        if (stored.Item.deleted?.BOOL === true) {
            return { status: 'deleted' }
        }
        const wrapped = stored.Item.wrapped_key?.B
        if (!wrapped?.length) {
            throw new Error('a v4 team month row has no wrapped key')
        }
        const decrypted = await this.kmsRequest(deadline, (abortSignal) =>
            this.kms.send(
                new DecryptCommand({
                    KeyId: this.kmsKeyArn,
                    CiphertextBlob: wrapped,
                    EncryptionContext: teamMonthWrappingContext(teamId, keyMonth),
                }),
                { abortSignal }
            )
        )
        if (decrypted.Plaintext?.length !== 32) {
            throw new Error('KMS returned an invalid v4 plaintext key')
        }
        return { status: 'ok', key: Buffer.from(decrypted.Plaintext) }
    }

    private async kmsRequest<T>(deadline: AbortSignal, send: (abortSignal: AbortSignal) => Promise<T>): Promise<T> {
        deadline.throwIfAborted()
        const admitted = this.kmsConcurrency(async () => {
            // A waiter whose deadline passed in the queue has already left, so its turn makes no KMS call.
            deadline.throwIfAborted()
            const now = Date.now()
            const scheduledAt = Math.max(now, this.nextKmsRequestAt)
            this.nextKmsRequestAt = scheduledAt + 1000 / this.kmsRequestsPerSecond
            if (scheduledAt > now) {
                await sleep(scheduledAt - now, undefined, { signal: deadline })
            }
            return await send(AbortSignal.any([deadline, AbortSignal.timeout(KMS_TIMEOUT_MS)]))
        })
        // The read budget also bounds the wait for a KMS turn and for the rate limit.
        return await untilAborted(admitted, deadline)
    }
}

/** Rejects with the signal's reason once it aborts, and leaves `work` to settle on its own. */
export async function untilAborted<T>(work: Promise<T>, signal: AbortSignal): Promise<T> {
    let onAbort!: () => void
    const aborted = new Promise<never>((_resolve, reject) => {
        onAbort = () => reject(signal.reason)
        if (signal.aborted) {
            onAbort()
        } else {
            signal.addEventListener('abort', onAbort, { once: true })
        }
    })
    try {
        return await Promise.race([work, aborted])
    } finally {
        signal.removeEventListener('abort', onAbort)
    }
}
