import { Properties } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { ProducerRecord } from 'kafkajs'
import { Counter } from 'prom-client'

import { defaultConfig } from '../../config/config'
import { KAFKA_PERSON } from '../../config/kafka-topics'
import {
    BasePerson,
    ClickHousePerson,
    Person,
    PluginLogEntryType,
    PluginLogLevel,
    RawPerson,
    TimestampFormat,
} from '../../types'
import { status } from '../../utils/status'
import { castTimestampOrNow } from '../../utils/utils'

export function unparsePersonPartial(person: Partial<Person>): Partial<RawPerson> {
    return { ...(person as BasePerson), ...(person.created_at ? { created_at: person.created_at.toISO() } : {}) }
}

export function escapeQuotes(input: string): string {
    return input.replace(/"/g, '\\"')
}

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
    context?: Record<string, any> | (() => Record<string, any>),
    timeout = defaultConfig.TASK_TIMEOUT * 1000,
    sendToSentry = true
): NodeJS.Timeout {
    return setTimeout(() => {
        const ctx = typeof context === 'function' ? context() : context
        status.warn('⌛', message, ctx)
        if (sendToSentry) {
            Sentry.captureMessage(message, ctx ? { extra: ctx } : undefined)
        }
    }, timeout)
}

// when changing this set, be sure to update the frontend as well (taxonomy.tsx (eventToPersonProperties))
const eventToPersonProperties = new Set([
    // mobile params
    '$app_build',
    '$app_name',
    '$app_namespace',
    '$app_version',
    // web params
    '$browser',
    '$browser_version',
    '$device_type',
    '$current_url',
    '$pathname',
    '$os',
    '$os_version',
    '$referring_domain',
    '$referrer',
    // campaign params - automatically added by posthog-js here https://github.com/PostHog/posthog-js/blob/master/src/utils/event-utils.ts
    'utm_source',
    'utm_medium',
    'utm_campaign',
    'utm_content',
    'utm_name',
    'utm_term',
    'gclid',
    'gad_source',
    'gbraid',
    'wbraid',
    'fbclid',
    'msclkid',
])

/** If we get new UTM params, make sure we set those  **/
export function personInitialAndUTMProperties(properties: Properties): Properties {
    const propertiesCopy = { ...properties }

    const propertiesForPerson: [string, any][] = Object.entries(properties).filter(([key]) =>
        eventToPersonProperties.has(key)
    )

    // all potential params are checked for $initial_ values and added to $set_once
    const maybeSetOnce: [string, any][] = propertiesForPerson.map(([key, value]) => [
        `$initial_${key.replace('$', '')}`,
        value,
    ])

    // all found are also then added to $set
    const maybeSet: [string, any][] = propertiesForPerson

    if (maybeSet.length > 0) {
        propertiesCopy.$set = { ...(properties.$set || {}), ...Object.fromEntries(maybeSet) }
    }
    if (maybeSetOnce.length > 0) {
        propertiesCopy.$set_once = { ...(properties.$set_once || {}), ...Object.fromEntries(maybeSetOnce) }
    }
    return propertiesCopy
}

export function generateKafkaPersonUpdateMessage(person: Person, isDeleted = false): ProducerRecord {
    return {
        topic: KAFKA_PERSON,
        messages: [
            {
                value: JSON.stringify({
                    id: person.uuid,
                    created_at: castTimestampOrNow(person.created_at, TimestampFormat.ClickHouseSecondPrecision),
                    properties: JSON.stringify(person.properties),
                    team_id: person.team_id,
                    is_identified: Number(person.is_identified),
                    is_deleted: Number(isDeleted),
                    version: person.version + (isDeleted ? 100 : 0), // keep in sync with delete_person in posthog/models/person/util.py
                } as Omit<ClickHousePerson, 'timestamp'>),
            },
        ],
    }
}

// Very useful for debugging queries
export function getFinalPostgresQuery(queryString: string, values: any[]): string {
    return queryString.replace(/\$([0-9]+)/g, (m, v) => JSON.stringify(values[parseInt(v) - 1]))
}

export function shouldStoreLog(pluginLogLevel: PluginLogLevel, type: PluginLogEntryType): boolean {
    switch (pluginLogLevel) {
        case PluginLogLevel.Full:
            return true
        case PluginLogLevel.Log:
            return type !== PluginLogEntryType.Debug
        case PluginLogLevel.Info:
            return type !== PluginLogEntryType.Log && type !== PluginLogEntryType.Debug
        case PluginLogLevel.Warn:
            return type === PluginLogEntryType.Warn || type === PluginLogEntryType.Error
        case PluginLogLevel.Critical:
            return type === PluginLogEntryType.Error
    }
}

// keep in sync with posthog/posthog/api/utils.py::safe_clickhouse_string
export function safeClickhouseString(str: string): string {
    // character is a surrogate
    return str.replace(/[\ud800-\udfff]/gu, (match) => {
        surrogatesSubstitutedCounter.inc()
        const res = JSON.stringify(match)
        return res.slice(1, res.length - 1) + `\\`
    })
}

// JSONB columns may not contain null bytes, so we replace them with the Unicode replacement
// character. This should be called before passing a parameter to a parameterized query. It is
// designed to safely ignore other types, since we have some functions that operate on generic
// parameter arrays.
//
// Objects are JSON serialized to make the replacement safer and less expensive, since we don't have
// to recursively walk the object once its a string. They need to be JSON serialized before sending
// to Postgres anyway.
export function sanitizeJsonbValue(value: any): any {
    if (value === null) {
        // typeof null is 'object', but we don't want to serialize it into a string below
        return value
    } else if (typeof value === 'object') {
        return JSON.stringify(value).replace(/\\u0000/g, '\\uFFFD')
    } else {
        return value
    }
}

export const surrogatesSubstitutedCounter = new Counter({
    name: 'surrogates_substituted_total',
    help: 'Stray UTF16 surrogates detected and removed from user input.',
})
