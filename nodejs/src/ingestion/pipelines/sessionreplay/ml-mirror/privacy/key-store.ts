import { TransactWriteItem } from '@aws-sdk/client-dynamodb'

import { sessionStartTimestampFromUuidV7 } from '~/ingestion/pipelines/sessionreplay/ml-mirror/session-identifier-format'

import { MlDataKey, MlKeyEncryption } from './crypto'
import { DynamoItem, MlPrivacyDynamoDB, encodeKey } from './dynamodb'
import {
    MlKeyIdentity,
    MlSessionIdentity,
    TableKey,
    associationIds,
    consentKeyId,
    distinctBlockId,
    imageKeyId,
    sessionKeyId,
    tableKeyString,
    teamBlockId,
} from './schema'

export interface MlSessionKeys {
    session: MlDataKey
    image: MlDataKey
}

function storedKeyId(identity: MlKeyIdentity): TableKey {
    return identity.sessionId
        ? sessionKeyId(identity.teamId, identity.sessionId)
        : imageKeyId(identity.teamId, identity.consentGrantedAt)
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

export class MlSessionKeyStore {
    constructor(
        private readonly db: MlPrivacyDynamoDB,
        private readonly encryption: MlKeyEncryption
    ) {}

    public async prepare(identities: MlSessionIdentity[]): Promise<MlKeyBatch> {
        const batch = new MlKeyBatch(this.db, this.encryption, identities)
        await batch.read()
        return batch
    }
}

export class MlKeyBatch {
    private state = new Map<string, DynamoItem>()
    private readonly candidates = new Map<string, MlDataKey>()
    private readonly keys = new Map<string, MlDataKey>()
    private readonly blocked = new Map<string, TableKey>()
    private readonly grants = new Map<string, number>()
    private committed = false

    constructor(
        private readonly db: MlPrivacyDynamoDB,
        private readonly encryption: MlKeyEncryption,
        private readonly identities: MlSessionIdentity[]
    ) {}

    public async read(): Promise<void> {
        this.keys.clear()
        this.blocked.clear()
        this.grants.clear()
        const initial = this.identities.flatMap((identity) => [
            consentKeyId(identity.organizationId),
            teamBlockId(identity.teamId),
            distinctBlockId(identity.teamId, identity.distinctId),
            sessionKeyId(identity.teamId, identity.sessionId),
        ])
        this.state = await this.db.read(initial)
        const keyIdentities = new Map<string, MlKeyIdentity>()
        for (const identity of this.identities) {
            const id = tableKeyString(sessionKeyId(identity.teamId, identity.sessionId))
            const consent = this.state.get(tableKeyString(consentKeyId(identity.organizationId)))
            const grantedAt = Number(consent?.granted_at?.N)
            const startedAt = sessionStartTimestampFromUuidV7(identity.sessionId)
            if (
                this.state.has(tableKeyString(distinctBlockId(identity.teamId, identity.distinctId))) ||
                this.state.has(tableKeyString(teamBlockId(identity.teamId)))
            ) {
                this.blocked.set(id, sessionKeyId(identity.teamId, identity.sessionId))
                continue
            }
            if (
                consent?.allowed?.BOOL !== true ||
                !Number.isSafeInteger(grantedAt) ||
                startedAt === null ||
                startedAt < grantedAt ||
                this.state.get(id)?.deleted?.BOOL === true
            ) {
                continue
            }
            this.grants.set(id, grantedAt)
            for (const sessionId of [identity.sessionId, undefined]) {
                const keyIdentity = {
                    teamId: identity.teamId,
                    organizationId: identity.organizationId,
                    consentGrantedAt: grantedAt,
                    ...(sessionId ? { sessionId } : {}),
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
                if (identity.sessionId && this.blocked.has(id)) {
                    return
                }
                const item = this.state.get(id)
                if (item?.deleted?.BOOL === true) {
                    return
                }
                if (item) {
                    if (
                        !item.wrapped_key?.B ||
                        item.organization_id?.S !== identity.organizationId ||
                        Number(item.granted_at?.N) !== identity.consentGrantedAt
                    ) {
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
        if (this.blocked.has(id)) {
            return undefined
        }
        const session = this.keys.get(id)
        if (!session) {
            return undefined
        }
        const image = this.keys.get(tableKeyString(imageKeyId(teamId, session.identity.consentGrantedAt)))
        return image ? { session, image } : undefined
    }

    private guards(identity: MlKeyIdentity): TransactWriteItem[] {
        return [
            this.db.check(teamBlockId(identity.teamId), 'attribute_not_exists(pk)'),
            this.db.check(consentKeyId(identity.organizationId), 'allowed = :allowed AND granted_at = :grant', {
                ':allowed': { BOOL: true },
                ':grant': { N: String(identity.consentGrantedAt) },
            }),
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
        const creations: TransactWriteItem[][] = []
        for (const [id, key] of this.keys) {
            if (this.state.has(id) || (key.identity.sessionId && this.blocked.has(id))) {
                continue
            }
            creations.push([
                ...this.guards(key.identity),
                this.put(
                    storedKeyId(key.identity),
                    {
                        wrapped_key: { B: key.wrapped },
                        granted_at: { N: String(key.identity.consentGrantedAt) },
                        organization_id: { S: key.identity.organizationId },
                        team_id: { N: String(key.identity.teamId) },
                    },
                    'attribute_not_exists(pk)'
                ),
                this.put(
                    { pk: `organization:${key.identity.organizationId}`, sk: `team:${key.identity.teamId}` },
                    { team_id: { N: String(key.identity.teamId) } }
                ),
            ])
        }
        await this.db.write(groupTransactions(creations))
        const associations: TransactWriteItem[][] = []
        for (const identity of this.identities) {
            const key = this.get(identity.teamId, identity.sessionId)?.session
            if (!key) {
                continue
            }
            const association = associationIds(identity)
            const attributes: DynamoItem = {
                session_id: { S: identity.sessionId },
                team_id: { N: String(identity.teamId) },
            }
            associations.push([
                ...this.guards(key.identity),
                this.db.check(distinctBlockId(identity.teamId, identity.distinctId), 'attribute_not_exists(pk)'),
                this.db.check(
                    sessionKeyId(identity.teamId, identity.sessionId),
                    'attribute_exists(wrapped_key) AND attribute_not_exists(deleted)'
                ),
                this.put(association.forward, attributes),
                this.put(association.reverse, { ...attributes, forward_pk: { S: association.forward.pk } }),
            ])
        }
        await this.db.write(groupTransactions(associations))
        await this.db.write(
            groupTransactions([...this.blocked.values()].map((key) => [this.put(key, { deleted: { BOOL: true } })]))
        )
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
