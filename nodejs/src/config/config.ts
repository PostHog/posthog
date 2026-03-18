import { getDefaultCdpConfig } from '../cdp/config'
import { getDefaultCommonConfig } from '../common/config'
import { getDefaultIngestionConsumerConfig } from '../ingestion/config'
import { getDefaultErrorTrackingConsumerConfig } from '../ingestion/error-tracking/config'
import {
    getDefaultLogsIngestionConsumerConfig,
    getDefaultTracesIngestionConsumerConfig,
} from '../logs-ingestion/config'
import { getDefaultSessionRecordingApiConfig, getDefaultSessionRecordingConfig } from '../session-recording/config'
import { PluginsServerConfig, ValueMatcher, stringToPluginServerMode } from '../types'
import { stringToBoolean } from '../utils/env-utils'

// Re-export for backwards compatibility
export { DEFAULT_HTTP_SERVER_PORT } from '../common/config'

export const defaultConfig = overrideWithEnv(getDefaultConfig())

export function getDefaultConfig(): PluginsServerConfig {
    return {
        ...getDefaultCommonConfig(),
        ...getDefaultCdpConfig(),
        ...getDefaultIngestionConsumerConfig(),
        ...getDefaultLogsIngestionConsumerConfig(),
        ...getDefaultTracesIngestionConsumerConfig(),
        ...getDefaultErrorTrackingConsumerConfig(),
        ...getDefaultSessionRecordingConfig(),
        ...getDefaultSessionRecordingApiConfig(),
    }
}

export function overrideWithEnv(
    config: PluginsServerConfig,
    env: Record<string, string | undefined> = process.env
): PluginsServerConfig {
    const defaults = getDefaultConfig() as any // to make typechecker happy to use defaults[key]

    const tmpConfig: any = { ...config }
    for (const key of Object.keys(config)) {
        if (typeof env[key] !== 'undefined') {
            if (key == 'PLUGIN_SERVER_MODE') {
                const mode = env[key]
                if (mode == null || mode in stringToPluginServerMode) {
                    tmpConfig[key] = env[key]
                } else {
                    throw Error(`Invalid PLUGIN_SERVER_MODE ${env[key]}`)
                }
            } else if (typeof defaults[key] === 'number') {
                tmpConfig[key] = env[key]?.indexOf('.') ? parseFloat(env[key]!) : parseInt(env[key]!)
            } else if (typeof defaults[key] === 'boolean') {
                tmpConfig[key] = stringToBoolean(env[key])
            } else {
                tmpConfig[key] = env[key]
            }
        }
    }
    const newConfig: PluginsServerConfig = { ...tmpConfig }

    if (!newConfig.DATABASE_URL && !newConfig.POSTHOG_DB_NAME) {
        throw Error(
            'You must specify either DATABASE_URL or the database options POSTHOG_DB_NAME, POSTHOG_DB_USER, POSTHOG_DB_PASSWORD, POSTHOG_POSTGRES_HOST, POSTHOG_POSTGRES_PORT!'
        )
    }

    if (!newConfig.DATABASE_URL) {
        const encodedUser = encodeURIComponent(newConfig.POSTHOG_DB_USER)
        const encodedPassword = encodeURIComponent(newConfig.POSTHOG_DB_PASSWORD)
        newConfig.DATABASE_URL = `postgres://${encodedUser}:${encodedPassword}@${newConfig.POSTHOG_POSTGRES_HOST}:${newConfig.POSTHOG_POSTGRES_PORT}/${newConfig.POSTHOG_DB_NAME}`
    }

    if (
        !newConfig.BEHAVIORAL_COHORTS_DATABASE_URL &&
        newConfig.POSTGRES_BEHAVIORAL_COHORTS_HOST &&
        newConfig.POSTGRES_BEHAVIORAL_COHORTS_USER &&
        newConfig.POSTGRES_BEHAVIORAL_COHORTS_PASSWORD
    ) {
        const encodedUser = encodeURIComponent(newConfig.POSTGRES_BEHAVIORAL_COHORTS_USER)
        const encodedPassword = encodeURIComponent(newConfig.POSTGRES_BEHAVIORAL_COHORTS_PASSWORD)
        newConfig.BEHAVIORAL_COHORTS_DATABASE_URL = `postgres://${encodedUser}:${encodedPassword}@${newConfig.POSTGRES_BEHAVIORAL_COHORTS_HOST}:5432/behavioral_cohorts`
    }

    return newConfig
}

export function buildIntegerMatcher(config: string | undefined, allowStar: boolean): ValueMatcher<number> {
    // Builds a ValueMatcher on a comma-separated list of values.
    // Optionally, supports a '*' value to match everything
    if (!config || config.trim().length == 0) {
        return () => false
    } else if (allowStar && config === '*') {
        return () => true
    } else {
        const values = new Set(
            config
                .split(',')
                .map((n) => parseInt(n))
                .filter((num) => !isNaN(num))
        )
        return (v: number) => {
            return values.has(v)
        }
    }
}

export function buildStringMatcher(config: string | undefined, allowStar: boolean): ValueMatcher<string> {
    // Builds a ValueMatcher on a comma-separated list of values.
    // Optionally, supports a '*' value to match everything
    if (!config || config.trim().length == 0) {
        return () => false
    } else if (allowStar && config === '*') {
        return () => true
    } else {
        const values = new Set(config.split(','))
        return (v: string) => {
            return values.has(v)
        }
    }
}
