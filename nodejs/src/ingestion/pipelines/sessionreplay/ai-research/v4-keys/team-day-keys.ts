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

/**
 * A team's key for one day. `missing` means no row: the recorder stores the row before it sends a URL, so the row
 * expired or was removed. `deleted` is a tombstone. In both cases the caller stores nothing.
 */
export type TeamDayKey = { status: 'ok'; key: Buffer } | { status: 'missing' } | { status: 'deleted' }

/** The KMS encryption context of a team day key. The Rust recorder and the key policy use the same one. */
export function teamDayWrappingContext(teamId: number, keyDay: string): Record<string, string> {
    return { key_day: keyDay, purpose: 'ai-research-v4', team_id: String(teamId) }
}

export function teamDayRowKey(teamId: number, keyDay: string): Item {
    return { pk: { S: `team:${teamId}` }, sk: { S: `day:${keyDay}` } }
}

/**
 * Reads the v4 team day keys in `ai-research-replay-v4-keys`. Only the recorder writes this table, so this class never
 * stores a key, and the caller drops an image whose team and day have no key.
 */
export class TeamDayKeys {
    private readonly cache = new LRUCache<string, TeamDayKey>({ max: 10_000, ttl: CACHE_LIFETIME_MS })
    private readonly pending = new Map<string, Promise<TeamDayKey>>()
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

    public async get(teamId: number, keyDay: string): Promise<TeamDayKey> {
        const id = `${teamId}:${keyDay}`
        const cached = this.cache.get(id)
        if (cached) {
            return cached
        }
        // Concurrent requests for one team and day share a read, so a burst of images makes one KMS call.
        let pending = this.pending.get(id)
        if (!pending) {
            pending = this.resolve(teamId, keyDay).then((key) => {
                // Only a key row and a tombstone are held, as in the v3 row cache.
                if (key.status !== 'missing') {
                    this.cache.set(id, key)
                }
                return key
            })
            this.pending.set(id, pending)
        }
        try {
            return await pending
        } finally {
            if (this.pending.get(id) === pending) {
                this.pending.delete(id)
            }
        }
    }

    private async resolve(teamId: number, keyDay: string): Promise<TeamDayKey> {
        const deadline = AbortSignal.timeout(this.readBudgetMs)
        const stored = await this.dynamo.send(
            new GetItemCommand({ TableName: this.tableName, Key: teamDayRowKey(teamId, keyDay), ConsistentRead: true }),
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
            throw new Error('a v4 team day row has no wrapped key')
        }
        const decrypted = await this.kmsRequest(deadline, (abortSignal) =>
            this.kms.send(
                new DecryptCommand({
                    KeyId: this.kmsKeyArn,
                    CiphertextBlob: wrapped,
                    EncryptionContext: teamDayWrappingContext(teamId, keyDay),
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
        let onAbort!: () => void
        const expired = new Promise<never>((_resolve, reject) => {
            onAbort = () => reject(deadline.reason)
            deadline.addEventListener('abort', onAbort, { once: true })
        })
        try {
            return await Promise.race([admitted, expired])
        } finally {
            deadline.removeEventListener('abort', onAbort)
        }
    }
}
