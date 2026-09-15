import { logger } from '~/common/utils/logger'
import { sessionStartMonth } from '~/ingestion/pipelines/sessionreplay/ml-mirror/session-identifier-format'

import { MlDataKey, MlKeyEncryption } from './crypto'
import { DynamoItem, MlPrivacyDynamoDB } from './dynamodb'
import {
    MlKeyIdentity,
    MlSessionIdentity,
    TableKey,
    imageKeyId,
    keySessionMonth,
    monthKeyIndexId,
    sessionKeyId,
    tableKeyString,
    teamBlockId,
} from './schema'

// Commits retry transient DynamoDB and KMS failures; the budget counts the re-reads as well as the waits and stays under the consumer's 60 s loop stall threshold.
const COMMIT_ATTEMPTS = 10
const COMMIT_BUDGET_MS = 45_000
const COMMIT_BACKOFF_BASE_MS = 100
const COMMIT_BACKOFF_CAP_MS = 3_000

function commitRetryDelayMs(attempt: number): number {
    return Math.random() * Math.min(COMMIT_BACKOFF_CAP_MS, COMMIT_BACKOFF_BASE_MS * 2 ** attempt)
}

export interface MlSessionKeys {
    session: MlDataKey
    image: MlDataKey
}

function storedKeyId(identity: MlKeyIdentity): TableKey {
    return identity.sessionId
        ? sessionKeyId(identity.teamId, identity.sessionId)
        : imageKeyId(identity.teamId, keySessionMonth(identity))
}

export class MlSessionKeyStore {
    constructor(
        private readonly db: MlPrivacyDynamoDB,
        private readonly encryption: MlKeyEncryption
    ) {}

    public async prepare(identities: MlSessionIdentity[]): Promise<MlKeyBatch> {
        const eligible = identities.filter((identity) => {
            try {
                sessionStartMonth(identity.sessionId)
                return true
            } catch {
                return false
            }
        })
        const batch = new MlKeyBatch(this.db, this.encryption, eligible)
        await batch.read()
        return batch
    }
}

export class MlKeyBatch {
    private state = new Map<string, DynamoItem>()
    private readonly candidates = new Map<string, MlDataKey>()
    private readonly keys = new Map<string, MlDataKey>()
    private committed = false

    constructor(
        private readonly db: MlPrivacyDynamoDB,
        private readonly encryption: MlKeyEncryption,
        private readonly identities: MlSessionIdentity[]
    ) {}

    public async read(): Promise<void> {
        this.keys.clear()
        const initial = this.identities.flatMap((identity) => [
            teamBlockId(identity.teamId),
            sessionKeyId(identity.teamId, identity.sessionId),
        ])
        this.state = await this.db.read(initial)
        const keyIdentities = new Map<string, MlKeyIdentity>()
        for (const identity of this.identities) {
            const id = tableKeyString(sessionKeyId(identity.teamId, identity.sessionId))
            if (
                this.state.has(tableKeyString(teamBlockId(identity.teamId))) ||
                this.state.get(id)?.deleted?.BOOL === true
            ) {
                continue
            }
            for (const sessionId of [identity.sessionId, undefined]) {
                const keyIdentity = {
                    teamId: identity.teamId,
                    organizationId: identity.organizationId,
                    ...(sessionId ? { sessionId } : { sessionMonth: sessionStartMonth(identity.sessionId) }),
                }
                keyIdentities.set(tableKeyString(storedKeyId(keyIdentity)), keyIdentity)
            }
        }
        const remaining = [...keyIdentities.values()].filter((identity) => !identity.sessionId).map(storedKeyId)
        for (const [id, item] of await this.db.read(remaining)) {
            this.state.set(id, item)
        }
        await Promise.all(
            [...keyIdentities].map(async ([id, identity]) => {
                const item = this.state.get(id)
                if (item?.deleted?.BOOL === true) {
                    return
                }
                if (item) {
                    if (!item.wrapped_key?.B || item.organization_id?.S !== identity.organizationId) {
                        throw new Error('Invalid stored ML key identity')
                    }
                    this.keys.set(id, await this.encryption.decrypt(identity, Buffer.from(item.wrapped_key.B)))
                } else {
                    let candidate = this.candidates.get(id)
                    if (!candidate) {
                        candidate = await this.encryption.generate(identity)
                        this.candidates.set(id, candidate)
                    }
                    this.keys.set(id, candidate)
                }
            })
        )
    }

    public get(teamId: number, sessionId: string): MlSessionKeys | undefined {
        const id = tableKeyString(sessionKeyId(teamId, sessionId))
        const session = this.keys.get(id)
        if (!session) {
            return undefined
        }
        const image = this.keys.get(tableKeyString(imageKeyId(teamId, sessionStartMonth(sessionId))))
        return image ? { session, image } : undefined
    }

    // A key and its month index entry are two plain writes instead of one transaction, so no commit in the fleet waits on another; the re-read afterwards adopts a competing writer's key and drops sessions or teams blocked during the batch.
    private async persist(): Promise<void> {
        await Promise.all(
            [...this.keys].map(async ([id, key]) => {
                if (this.state.has(id)) {
                    return
                }
                const location = storedKeyId(key.identity)
                const created = await this.db.putIfAbsent(location, {
                    wrapped_key: { B: key.wrapped },
                    organization_id: { S: key.identity.organizationId },
                    team_id: { N: String(key.identity.teamId) },
                    session_month: { S: keySessionMonth(key.identity) },
                })
                if (!created) {
                    return
                }
                this.encryption.rememberCommitted(key)
                await this.db.put(monthKeyIndexId(key.identity, location), {
                    key_pk: { S: location.pk },
                    key_sk: { S: location.sk },
                })
            })
        )
        await this.read()
    }

    public async commit(): Promise<void> {
        if (this.committed) {
            throw new Error('ML batch already committed')
        }
        const startedAt = Date.now()
        for (let attempt = 0; attempt < COMMIT_ATTEMPTS; attempt++) {
            try {
                await this.persist()
                for (const key of this.keys.values()) {
                    this.encryption.rememberCommitted(key)
                }
                this.committed = true
                return
            } catch (error) {
                const delayMs = commitRetryDelayMs(attempt)
                if (attempt === COMMIT_ATTEMPTS - 1 || Date.now() - startedAt + delayMs > COMMIT_BUDGET_MS) {
                    throw error
                }
                logger.warn('🔑', 'ml_key_commit_retry', {
                    attempt: attempt + 1,
                    code: error instanceof Error ? error.name : undefined,
                    error: String(error),
                })
                await new Promise((resolve) => setTimeout(resolve, delayMs))
                await this.read()
            }
        }
    }
}
