export const MMDB_ENDPOINT = 'https://mmdb.posthog.net/'
export const MMDB_ATTACHMENT_KEY = '@posthog/mmdb'
export const MMDB_STALE_AGE_DAYS = 45
export const MMDB_STATUS_REDIS_KEY = '@posthog-plugin-server/mmdb-status'
export const MMDB_INTERNAL_SERVER_TIMEOUT_SECONDS = 10

export enum MMDBRequestStatus {
    TimedOut = 'Internal MMDB server connection timed out!',
    ServiceUnavailable = 'IP location capabilities are not available in this PostHog instance!',
    OK = 'OK',
}
