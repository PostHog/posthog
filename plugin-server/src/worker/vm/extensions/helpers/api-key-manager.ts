import { DB } from '../../../../utils/db/db'
import { timeoutGuard } from '../../../../utils/db/utils'
import { generateRandomToken, getByAge, UUIDT } from '../../../../utils/utils'
import { RawOrganization } from './../../../../types'

type PluginsApiKeyCache<T> = Map<RawOrganization['id'], [T, number]>

const POSTHOG_BOT_USER_EMAIL_DOMAIN = 'posthogbot.user'

export class PluginsApiKeyManager {
    db: DB
    pluginsApiKeyCache: PluginsApiKeyCache<string | null>

    constructor(db: DB) {
        this.db = db
        this.pluginsApiKeyCache = new Map()
    }

    public async fetchOrCreatePersonalApiKey(organizationId: RawOrganization['id']): Promise<string> {
        const createNewKey = async (userId: number): Promise<string> => {
            return (
                await this.db.createPersonalApiKey({
                    id: generateRandomToken(32),
                    user_id: userId,
                    label: 'autogen',
                    value: `phx_${generateRandomToken(32)}`,
                    created_at: new Date(),
                })
            ).rows[0].value
        }

        const cachedKey = getByAge(this.pluginsApiKeyCache, organizationId)
        if (cachedKey) {
            return cachedKey
        }

        const timeout = timeoutGuard(`Still running "fetchOrCreatePersonalApiKey". Timeout warning after 30 sec!`)
        try {
            let key: string | null = null
            const userResult = await this.db.postgresQuery(
                `SELECT id FROM posthog_user WHERE email LIKE $1`,
                [`%@${POSTHOG_BOT_USER_EMAIL_DOMAIN}`],
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
                })

                key = await createNewKey(newUserResult.rows[0].id)
            } else {
                // User exists, check if the key does too
                const userId = userResult.rows[0].id
                const personalApiKeyResult = await this.db.postgresQuery(
                    'SELECT value FROM posthog_personalapikey WHERE user_id = $1',
                    [userId],
                    'fetchOrCreatePersonalApiKey'
                )

                // user remains but key was somehow deleted
                if (!personalApiKeyResult.rows.length || !personalApiKeyResult.rows[0].value) {
                    key = await createNewKey(userId)
                } else {
                    key = personalApiKeyResult.rows[0].value
                }
            }

            if (!key) {
                throw new Error('Unable to find or create a Personal API Key')
            }

            this.pluginsApiKeyCache.set(organizationId, [key, Date.now()])

            return key
        } finally {
            clearTimeout(timeout)
        }
    }
}
