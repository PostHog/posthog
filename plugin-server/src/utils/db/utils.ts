import { Properties } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { ProducerRecord } from 'kafkajs'
import { DateTime } from 'luxon'

import { defaultConfig } from '../../config/config'
import { KAFKA_PERSON } from '../../config/kafka-topics'
import { BasePerson, Person, RawPerson, TimestampFormat } from '../../types'
import { castTimestampOrNow } from '../../utils/utils'
import { PluginLogEntrySource, PluginLogEntryType, PluginLogLevel } from './../../types'

export function unparsePersonPartial(person: Partial<Person>): Partial<RawPerson> {
    return { ...(person as BasePerson), ...(person.created_at ? { created_at: person.created_at.toISO() } : {}) }
}

export function escapeQuotes(input: string): string {
    return input.replace(/"/g, '\\"')
}

// eslint-disable-next-line @typescript-eslint/explicit-module-boundary-types
export function sanitizeEventName(eventName: any): string {
    if (typeof eventName !== 'string') {
        try {
            eventName = JSON.stringify(eventName)
        } catch {
            eventName = String(eventName)
        }
    }
    return eventName.substr(0, 200)
}

export function timeoutGuard(
    message: string,
    context?: Record<string, any>,
    timeout = defaultConfig.TASK_TIMEOUT * 1000
): NodeJS.Timeout {
    return setTimeout(() => {
        console.log(`⌛⌛⌛ ${message}`, context)
        Sentry.captureMessage(message, context ? { extra: context } : undefined)
    }, timeout)
}

const campaignParams = new Set([
    'utm_source',
    'utm_medium',
    'utm_campaign',
    'utm_content',
    'utm_term',
    'gclid',
    'fbclid',
])
const initialParams = new Set([
    '$browser',
    '$browser_version',
    '$device_type',
    '$current_url',
    '$pathname',
    '$os',
    '$referring_domain',
    '$referrer',
])
const combinedParams = new Set([...campaignParams, ...initialParams])

/** If we get new UTM params, make sure we set those  **/
export function personInitialAndUTMProperties(properties: Properties): Properties {
    const propertiesCopy = { ...properties }
    const maybeSet = Object.entries(properties).filter(([key]) => campaignParams.has(key))

    const maybeSetInitial = Object.entries(properties)
        .filter(([key]) => combinedParams.has(key))
        .map(([key, value]) => [`$initial_${key.replace('$', '')}`, value])
    if (Object.keys(maybeSet).length > 0) {
        propertiesCopy.$set = { ...(properties.$set || {}), ...Object.fromEntries(maybeSet) }
    }
    if (Object.keys(maybeSetInitial).length > 0) {
        propertiesCopy.$set_once = { ...(properties.$set_once || {}), ...Object.fromEntries(maybeSetInitial) }
    }
    return propertiesCopy
}

export function generateKafkaPersonUpdateMessage(
    createdAt: DateTime | string,
    properties: Properties,
    teamId: number,
    isIdentified: boolean,
    id: string,
    version: number | null,
    isDeleted = 0
): ProducerRecord {
    return {
        topic: KAFKA_PERSON,
        messages: [
            {
                value: Buffer.from(
                    JSON.stringify({
                        id,
                        created_at: castTimestampOrNow(createdAt, TimestampFormat.ClickHouseSecondPrecision),
                        properties: JSON.stringify(properties),
                        team_id: teamId,
                        is_identified: isIdentified,
                        is_deleted: isDeleted,
                        ...(version !== null ? { version } : {}),
                    })
                ),
            },
        ],
    }
}

// Very useful for debugging queries
export function getFinalPostgresQuery(queryString: string, values: any[]): string {
    return queryString.replace(/\$([0-9]+)/g, (m, v) => JSON.stringify(values[parseInt(v) - 1]))
}

export function shouldStoreLog(
    pluginLogLevel: PluginLogLevel,
    source: PluginLogEntrySource,
    type: PluginLogEntryType
): boolean {
    if (source === PluginLogEntrySource.System) {
        return true
    }

    if (pluginLogLevel === PluginLogLevel.Critical) {
        return type === PluginLogEntryType.Error
    } else if (pluginLogLevel === PluginLogLevel.Warn) {
        return type !== PluginLogEntryType.Log && type !== PluginLogEntryType.Info
    } else if (pluginLogLevel === PluginLogLevel.Debug) {
        return type !== PluginLogEntryType.Log
    }

    return true
}

// keep in sync with posthog/posthog/api/utils.py::safe_clickhouse_string
export function safeClickhouseString(str: string): string {
    // character is a surrogate
    return str.replace(/[\ud800-\udfff]/gu, (match) => {
        const res = JSON.stringify(match)
        return res.slice(1, res.length - 1) + `\\`
    })
}
