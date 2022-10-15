import crypto from 'crypto'

import { DB } from '../../../../utils/db/db'
import { timeoutGuard } from '../../../../utils/db/utils'
import { generateRandomToken, UUIDT } from '../../../../utils/utils'
import { createCache } from '../cache'
import { OrganizationMembershipLevel, PluginConfig, RawOrganization } from './../../../../types'

const POSTHOG_BOT_USER_EMAIL_DOMAIN = 'posthogbot.user'
const PERSONAL_API_KEY_SALT = 'posthog_personal_api_key'

const getSecureValue = () => {
    const iterations = 480000
    const hash = crypto
        .pbkdf2Sync(`phx_${generateRandomToken(32)}`, PERSONAL_API_KEY_SALT, iterations, 24, 'sha256')
        .toString('hex')
    return `pbkdf2_sha256$${iterations}$${PERSONAL_API_KEY_SALT}$${hash}`
}

export class PluginsApiKeyManager {
    db: DB

    constructor(db: DB) {
        this.db = db
    }

    public async fetchOrCreatePersonalApiKey(
        organizationId: RawOrganization['id'],
        pluginConfig: PluginConfig
    ): Promise<string> {
        const createNewKey = async (userId: number): Promise<string> => {
            return (
                await this.db.createPersonalApiKey({
                    id: generateRandomToken(32),
                    user_id: userId,
                    label: 'autogen',
                    secure_value: getSecureValue(),
                    created_at: new Date(),
                })
            ).rows[0].secure_value
        }
        const cache = createCache({ db: this.db } as any, pluginConfig.plugin_id, pluginConfig.team_id)

        const cachedKey = await cache.get('_bot_api_key', false)
        if (cachedKey) {
            return cachedKey as string
        }

        const timeout = timeoutGuard(`Still running "fetchOrCreatePersonalApiKey". Timeout warning after 30 sec!`)
        try {
            let key: string | null = null
            const userResult = await this.db.postgresQuery(
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
                throw new Error('Unable to find or create a Personal API Key')
            }

            await cache.set('_bot_api_key', key)

            return key
        } finally {
            clearTimeout(timeout)
        }
    }
}
