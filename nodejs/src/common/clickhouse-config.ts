import { isTestEnv } from '~/common/utils/env-utils'

/**
 * Shared ClickHouse connection config. Service configs that need to talk to
 * ClickHouse compose this type into their own (e.g. `SessionRecordingApiConfig`,
 * `CdpConfig`) so the field set stays in lockstep across services and a service
 * can't silently end up with `undefined` host/db at runtime.
 *
 * Usage:
 *   export type MyServiceConfig = ClickhouseConfig & { ... }
 *   export function getDefaultMyServiceConfig(): MyServiceConfig {
 *       return { ...getDefaultClickhouseConfig(), ... }
 *   }
 */
export type ClickhouseConfig = {
    CLICKHOUSE_HOST: string
    CLICKHOUSE_DATABASE: string
    CLICKHOUSE_USER: string
    CLICKHOUSE_PASSWORD: string | undefined
    CLICKHOUSE_SECURE: boolean
}

export function getDefaultClickhouseConfig(): ClickhouseConfig {
    return {
        CLICKHOUSE_HOST: 'localhost',
        // Test runs use the migrated test database — without this default,
        // services that talk to ClickHouse in tests would silently connect to
        // the empty `default` database and find no rows.
        CLICKHOUSE_DATABASE: isTestEnv() ? 'posthog_test' : 'default',
        CLICKHOUSE_USER: 'default',
        CLICKHOUSE_PASSWORD: undefined,
        CLICKHOUSE_SECURE: false,
    }
}
