import type { CommonConfig } from '~/common/config'

export type PosthogDatabaseUrlConfig = Pick<
    CommonConfig,
    | 'DATABASE_URL'
    | 'POSTHOG_DB_NAME'
    | 'POSTHOG_DB_USER'
    | 'POSTHOG_DB_PASSWORD'
    | 'POSTHOG_POSTGRES_HOST'
    | 'POSTHOG_POSTGRES_PORT'
>

export function buildPosthogDatabaseUrl(config: PosthogDatabaseUrlConfig): string {
    if (config.DATABASE_URL) {
        return config.DATABASE_URL
    }

    if (!config.POSTHOG_DB_NAME) {
        throw Error(
            'You must specify either DATABASE_URL or the database options POSTHOG_DB_NAME, POSTHOG_DB_USER, POSTHOG_DB_PASSWORD, POSTHOG_POSTGRES_HOST, POSTHOG_POSTGRES_PORT!'
        )
    }

    const encodedUser = encodeURIComponent(config.POSTHOG_DB_USER)
    const encodedPassword = encodeURIComponent(config.POSTHOG_DB_PASSWORD)
    return `postgres://${encodedUser}:${encodedPassword}@${config.POSTHOG_POSTGRES_HOST}:${config.POSTHOG_POSTGRES_PORT}/${config.POSTHOG_DB_NAME}`
}
