import { getDefaultAIObservabilityConfig } from '~/ai-observability/config'
import { getDefaultCdpConfig } from '~/cdp/config'
import {
    getDefaultKafkaWarehouseProducerEnvConfig,
    getDefaultKafkaWarpstreamCalculatedEventsProducerEnvConfig,
    getDefaultKafkaWarpstreamCyclotronProducerEnvConfig,
    getDefaultKafkaWarpstreamIngestionProducerEnvConfig,
} from '~/cdp/outputs/producers'
import { getDefaultCommonConfig } from '~/common/config'
import { getDefaultLogsIngestionConsumerConfig, getDefaultTracesIngestionConsumerConfig } from '~/logs/config'
import { PluginsServerConfig, ValueMatcher, stringToPluginServerMode } from '~/types'

import { stringToBoolean } from '../utils/env-utils'

// Re-export for backwards compatibility
export { DEFAULT_HTTP_SERVER_PORT } from '~/common/config'

export const defaultConfig = overrideWithEnv(getDefaultConfig())

export function getDefaultConfig(): PluginsServerConfig {
    return {
        ...getDefaultCommonConfig(),
        ...getDefaultCdpConfig(),
        ...getDefaultAIObservabilityConfig(),
        ...getDefaultLogsIngestionConsumerConfig(),
        ...getDefaultTracesIngestionConsumerConfig(),
        ...getDefaultKafkaWarpstreamIngestionProducerEnvConfig(),
        ...getDefaultKafkaWarpstreamCalculatedEventsProducerEnvConfig(),
        ...getDefaultKafkaWarpstreamCyclotronProducerEnvConfig(),
        ...getDefaultKafkaWarehouseProducerEnvConfig(),
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

/**
 * Builds a matcher that supports team IDs and/or percentage-based rollout.
 *
 * Formats:
 *   ''          → no match
 *   '*'         → match all
 *   '123,456'   → only teams 123 and 456
 *   '*:0.1'     → 10% of all traffic (random per call)
 *   '123,*:0.05' → team 123 always + 5% of all other teams
 */
export function buildIntegerMatcherWithPercentage(config: string | undefined): ValueMatcher<number> {
    if (!config || config.trim().length === 0) {
        return () => false
    }
    if (config.trim() === '*') {
        return () => true
    }

    const parts = config.split(',').map((s) => s.trim())
    const teamIds = new Set<number>()
    let percentage = 0

    for (const part of parts) {
        if (part.startsWith('*:')) {
            percentage = parseFloat(part.slice(2))
        } else {
            const num = parseInt(part)
            if (!isNaN(num)) {
                teamIds.add(num)
            }
        }
    }

    return (teamId: number) => {
        if (teamIds.has(teamId)) {
            return true
        }
        if (percentage > 0) {
            return Math.random() < percentage
        }
        return false
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
