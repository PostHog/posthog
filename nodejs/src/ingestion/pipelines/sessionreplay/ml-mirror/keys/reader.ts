import { MlDataKey, MlKeyEncryption } from './crypto'
import { MlKeyDynamoDB } from './dynamodb'
import { MlKeyIdentity, TableKey, tableKeyString, teamBlockId } from './schema'

export class MlKeyReader {
    constructor(
        private readonly db: MlKeyDynamoDB,
        private readonly encryption: MlKeyEncryption
    ) {}

    public async read(keys: TableKey[]): Promise<Map<string, MlDataKey>> {
        const stored = await this.db.read(keys)
        const identities = new Map<string, MlKeyIdentity>()
        for (const [id, item] of stored) {
            if (!item.wrapped_key?.B || item.deleted?.BOOL === true) {
                continue
            }
            const teamId = Number(item.team_id?.N)
            const organizationId = item.organization_id?.S
            if (!Number.isSafeInteger(teamId) || !organizationId) {
                throw new Error('Invalid ML key record')
            }
            const sessionId = item.sk.S?.startsWith('session:') ? item.sk.S.slice('session:'.length) : undefined
            identities.set(id, {
                teamId,
                organizationId,
                ...(sessionId ? { sessionId } : { sessionMonth: item.session_month?.S }),
            })
        }
        const state = await this.db.read([...identities.values()].map((identity) => teamBlockId(identity.teamId)))
        const result = new Map<string, MlDataKey>()
        await Promise.all(
            [...identities].map(async ([id, identity]) => {
                if (state.has(tableKeyString(teamBlockId(identity.teamId)))) {
                    return
                }
                result.set(id, await this.encryption.decrypt(identity, Buffer.from(stored.get(id)!.wrapped_key.B!)))
            })
        )
        return result
    }
}
