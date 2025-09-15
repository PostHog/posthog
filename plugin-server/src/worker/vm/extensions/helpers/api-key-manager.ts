import crypto from 'crypto'

import { DB } from '../../../../utils/db/db'
import { PostgresUse } from '../../../../utils/db/postgres'
import { timeoutGuard } from '../../../../utils/db/utils'
import { UUIDT, generateRandomToken } from '../../../../utils/utils'
import { OrganizationMembershipLevel, RawOrganization } from './../../../../types'

const POSTHOG_BOT_USER_EMAIL_DOMAIN = 'posthogbot.user'
const PERSONAL_API_KEY_SALT = 'posthog_personal_api_key'

function generatePersonalApiKeyValue(): [string, string] {
    const value = `phx_${generateRandomToken(32)}`
    const iterations = 260000
    const hash = crypto.pbkdf2Sync(value, PERSONAL_API_KEY_SALT, iterations, 32, 'sha256').toString('base64')
    const secureValue = `pbkdf2_sha256$${iterations}$${PERSONAL_API_KEY_SALT}$${hash}`
    return [value, secureValue]
}

export class PluginsApiKeyManager {
    db: DB

    constructor(db: DB) {
        this.db = db
    }

    public async fetchOrCreatePersonalApiKey(organizationId: RawOrganization['id']): Promise<string> {
        const createNewKey = async (userId: number): Promise<string> => {
            const [value, secureValue] = generatePersonalApiKeyValue()
            await this.db.createPersonalApiKey({
                id: generateRandomToken(32),
                user_id: userId,
                label: 'autogen',
                secure_value: secureValue,
                created_at: new Date(),
            })
            return value
        }

        const cachedKeyRedisKey = `plugins-api-key-manager/${organizationId}`
        const cachedKey = await this.db.redisGet<string | null>(cachedKeyRedisKey, null, 'fetchOrCreatePersonalApiKey')
        if (cachedKey) {
            return cachedKey as string
        }

        const timeout = timeoutGuard(`Still running "fetchOrCreatePersonalApiKey". Timeout warning after 30 sec!`)
        try {
            let key: string | null = null
            const userResult = await this.db.postgres.query(
                PostgresUse.COMMON_WRITE, // Happens on redis cache miss, so let's use the master to reduce races between pods
                `SELECT id FROM posthog_user WHERE current_organization_id = $1 AND email LIKE $2`,
                [organizationId, `%@${POSTHOG_BOT_USER_EMAIL_DOMAIN}`],
                'fetchPluginsUser'
            )

            if (userResult.rowCount < 1) {
                const botUserEmailId = Math.round(Math.random() * 100000000)
                const botUserEmail = `${botUserEmailId}@${POSTHOG_BOT_USER_EMAIL_DOMAIN}`

                // No user yet, provision a user and a key
                const newUserResult = await this.db.createUser({
                    uuid: new UUIDT(),
                    password: generateRandomToken(32),
                    first_name: 'Plugins API User [Bot]',
                    last_name: '',
                    email: botUserEmail,
                    distinct_id: generateRandomToken(32),
                    is_staff: false,
                    is_active: true,
                    date_joined: new Date(),
                    events_column_config: { active: 'DEFAULT' },
                    organization_id: organizationId,
                    organizationMembershipLevel: OrganizationMembershipLevel.Admin,
                })

                key = await createNewKey(newUserResult.rows[0].id)
            } else {
                // User exists, we'll need to create a new key
                const userId = userResult.rows[0].id
                key = await createNewKey(userId)
            }

            if (!key) {
                throw new Error('Unable to find or create a personal API key')
            }

            await this.db.redisSet(cachedKeyRedisKey, key, 'fetchOrCreatePersonalApiKey', 86_400 * 14) // Don't cache keys longer than 14 days

            return key
        } finally {
            clearTimeout(timeout)
        }
    }
}
