import { TransactWriteItem } from '@aws-sdk/client-dynamodb'

import { sessionStartMonth } from '~/ingestion/pipelines/sessionreplay/ml-mirror/session-identifier-format'

import { MlDataKey, MlKeyEncryption } from './crypto'
import { DynamoItem, MlPrivacyDynamoDB, encodeKey } from './dynamodb'
import {
    MlKeyIdentity,
    MlSessionIdentity,
    TableKey,
    blockShard,
    imageKeyId,
    keySessionMonth,
    monthBlockId,
    monthBlockShardId,
    monthKeyIndexId,
    sessionKeyId,
    tableKeyString,
    teamBlockId,
    teamBlockShardId,
} from './schema'

export interface MlSessionKeys {
    session: MlDataKey
    image: MlDataKey
}

function storedKeyId(identity: MlKeyIdentity): TableKey {
    return identity.sessionId
        ? sessionKeyId(identity.teamId, identity.sessionId)
        : imageKeyId(identity.teamId, keySessionMonth(identity))
}

function actionId(action: TransactWriteItem): string {
    const operation = action.ConditionCheck ?? action.Put ?? action.Update ?? action.Delete
    if (!operation) {
        throw new Error('Empty ML privacy transaction action')
    }
    const key = 'Item' in operation ? operation.Item : 'Key' in operation ? operation.Key : undefined
    if (!key?.pk?.S || !key.sk?.S) {
        throw new Error('Missing ML privacy transaction key')
    }
    return JSON.stringify([key.pk.S, key.sk.S])
}

export function groupTransactions(units: TransactWriteItem[][]): TransactWriteItem[][] {
    const transactions: TransactWriteItem[][] = []
    let current = new Map<string, TransactWriteItem>()
    for (const unit of units) {
        const next = new Map(current)
        for (const action of unit) {
            const id = actionId(action)
            const existing = next.get(id)
            if (existing && JSON.stringify(existing) !== JSON.stringify(action)) {
                throw new Error('Conflicting ML privacy transaction actions')
            }
            next.set(id, action)
        }
        if (next.size > 100 || Buffer.byteLength(JSON.stringify([...next.values()])) > 3_500_000) {
            if (!current.size) {
                throw new Error('ML privacy transaction unit exceeds limits')
            }
            transactions.push([...current.values()])
            current = new Map(unit.map((action) => [actionId(action), action]))
        } else {
            current = next
        }
    }
    if (current.size) {
        transactions.push([...current.values()])
    }
    return transactions
}

function addUnit(unitsByShard: Map<number, TransactWriteItem[][]>, shard: number, unit: TransactWriteItem[]): void {
    const units = unitsByShard.get(shard)
    if (units) {
        units.push(unit)
    } else {
        unitsByShard.set(shard, [unit])
    }
}

// A transaction never spans two shards, so commits across the fleet contend per shard instead of on one marker item.
function shardedTransactions(unitsByShard: Map<number, TransactWriteItem[][]>): TransactWriteItem[][] {
    return [...unitsByShard.values()].flatMap(groupTransactions)
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
            ...this.blockMarkerIds(identity),
            sessionKeyId(identity.teamId, identity.sessionId),
        ])
        this.state = await this.db.read(initial)
        const keyIdentities = new Map<string, MlKeyIdentity>()
        for (const identity of this.identities) {
            const id = tableKeyString(sessionKeyId(identity.teamId, identity.sessionId))
            if (this.blocked(identity) || this.state.get(id)?.deleted?.BOOL === true) {
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

    // The unsharded markers predate sharding and gate a batch at read time only; a commit guards on the shard markers that deletion writes alongside them.
    private blockMarkerIds(identity: MlSessionIdentity): TableKey[] {
        const month = sessionStartMonth(identity.sessionId)
        const shard = blockShard(identity)
        return [
            monthBlockId(month),
            teamBlockId(identity.teamId),
            monthBlockShardId(month, shard),
            teamBlockShardId(identity.teamId, shard),
        ]
    }

    private blocked(identity: MlSessionIdentity): boolean {
        return this.blockMarkerIds(identity).some((key) => this.state.has(tableKeyString(key)))
    }

    private guards(identity: MlKeyIdentity): TransactWriteItem[] {
        const shard = blockShard(identity)
        return [
            this.db.check(monthBlockShardId(keySessionMonth(identity), shard), 'attribute_not_exists(pk)'),
            this.db.check(teamBlockShardId(identity.teamId, shard), 'attribute_not_exists(pk)'),
        ]
    }

    private put(key: TableKey, attributes: DynamoItem, condition?: string): TransactWriteItem {
        return {
            Put: {
                TableName: this.db.tableName,
                Item: { ...encodeKey(key), ...attributes },
                ...(condition ? { ConditionExpression: condition } : {}),
            },
        }
    }

    private async persist(): Promise<void> {
        const creations = new Map<number, TransactWriteItem[][]>()
        for (const [id, key] of this.keys) {
            if (this.state.has(id)) {
                continue
            }
            addUnit(creations, blockShard(key.identity), [
                ...this.guards(key.identity),
                this.put(
                    storedKeyId(key.identity),
                    {
                        wrapped_key: { B: key.wrapped },
                        organization_id: { S: key.identity.organizationId },
                        team_id: { N: String(key.identity.teamId) },
                        session_month: { S: keySessionMonth(key.identity) },
                    },
                    'attribute_not_exists(pk)'
                ),
                this.put(monthKeyIndexId(key.identity, storedKeyId(key.identity)), {
                    key_pk: { S: storedKeyId(key.identity).pk },
                    key_sk: { S: storedKeyId(key.identity).sk },
                }),
            ])
        }
        await this.db.write(shardedTransactions(creations))
        const validations = new Map<number, TransactWriteItem[][]>()
        for (const identity of this.identities) {
            const key = this.get(identity.teamId, identity.sessionId)?.session
            if (!key) {
                continue
            }
            addUnit(validations, blockShard(key.identity), [
                ...this.guards(key.identity),
                this.db.check(
                    sessionKeyId(identity.teamId, identity.sessionId),
                    'attribute_exists(wrapped_key) AND attribute_not_exists(deleted)'
                ),
            ])
        }
        await this.db.write(shardedTransactions(validations))
    }

    public async commit(): Promise<void> {
        if (this.committed) {
            throw new Error('ML batch already committed')
        }
        for (let attempt = 0; attempt < 5; attempt++) {
            try {
                await this.persist()
                for (const key of this.keys.values()) {
                    this.encryption.rememberCommitted(key)
                }
                this.committed = true
                return
            } catch (error) {
                if (attempt === 4) {
                    throw error
                }
                await this.db.backoff(attempt)
                await this.read()
            }
        }
    }
}
