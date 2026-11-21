import fs from 'fs'
import https from 'https'

import { isTestEnv } from '~/common/utils/env-utils'
import { logger } from '~/common/utils/logger'

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
    // Django defaults this to true. The default is false here so that a deployment whose ClickHouse
    // certificate does not validate keeps connecting without setting it.
    CLICKHOUSE_VERIFY: boolean
    // Path to a PEM bundle, as in Django. When set, it replaces the default trust store.
    CLICKHOUSE_CA: string
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
        CLICKHOUSE_VERIFY: false,
        CLICKHOUSE_CA: '',
    }
}

export function createClickhouseHttpsAgent(
    config: Pick<ClickhouseConfig, 'CLICKHOUSE_VERIFY' | 'CLICKHOUSE_CA'>
): https.Agent {
    if (config.CLICKHOUSE_CA && !config.CLICKHOUSE_VERIFY) {
        logger.warn(
            'CLICKHOUSE_CA is ignored because CLICKHOUSE_VERIFY is false: the ClickHouse certificate is not verified'
        )
    }
    const ca = config.CLICKHOUSE_VERIFY && config.CLICKHOUSE_CA ? fs.readFileSync(config.CLICKHOUSE_CA) : undefined
    return new https.Agent({ rejectUnauthorized: config.CLICKHOUSE_VERIFY, ca, keepAlive: true, maxSockets: 10 })
}
