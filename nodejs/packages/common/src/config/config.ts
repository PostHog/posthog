import { CommonConfig, getDefaultCommonConfig } from '~/config'
import { PluginsServerConfig, ValueMatcher, stringToPluginServerMode } from '~/types'

import { stringToBoolean } from '../utils/env-utils'
import { buildBehavioralCohortsDatabaseUrl, buildPosthogDatabaseUrl } from './database-url'

// Re-export for backwards compatibility
export { DEFAULT_HTTP_SERVER_PORT } from '~/config'

// The common settings read from the environment. A service merges its own settings on top with overrideWithEnv.
export const defaultConfig: PluginsServerConfig = overrideWithEnv(getDefaultCommonConfig())

export function getDefaultConfig(): PluginsServerConfig {
    return getDefaultCommonConfig()
}

export function overrideWithEnv<T extends CommonConfig>(
    config: T,
    env: Record<string, string | undefined> = process.env
): T {
    // The config passed in carries the defaults, so its value types drive the coercion of each env var.
    const defaults = config as any

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
    const newConfig: T = { ...tmpConfig }

    // A service that never opens Postgres runs without database settings, so PostgresRouter reports a missing URL instead.
    if (newConfig.DATABASE_URL || newConfig.POSTHOG_DB_NAME) {
        newConfig.DATABASE_URL = buildPosthogDatabaseUrl(newConfig)
    }

    newConfig.BEHAVIORAL_COHORTS_DATABASE_URL = buildBehavioralCohortsDatabaseUrl(newConfig)

    return newConfig
}

/**
 * Override config values from environment variables. Works on any config object —
 * iterates its keys, reads matching env vars, and coerces based on the default value type.
 *
 * Unlike `overrideWithEnv`, this has no PluginsServerConfig-specific validation.
 * Use for server-local config types (e.g. KafkaDownstreamProducerEnvConfig, IngestionOutputsConfig).
 */
export function overrideConfigWithEnv<T extends Record<string, unknown>>(
    config: T,
    env: Record<string, string | undefined> = process.env
): T {
    const result: any = { ...config }
    for (const key of Object.keys(config)) {
        if (typeof env[key] !== 'undefined') {
            const defaultValue = config[key]
            if (typeof defaultValue === 'number') {
                result[key] = env[key]?.indexOf('.') ? parseFloat(env[key]!) : parseInt(env[key]!)
            } else if (typeof defaultValue === 'boolean') {
                result[key] = stringToBoolean(env[key])
            } else {
                result[key] = env[key]
            }
        }
    }
    return result
}

// These live in ./matchers because importing this module builds defaultConfig, which throws without database env.
export { buildIntegerMatcher, buildIntegerMatcherWithPercentage } from './matchers'

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
