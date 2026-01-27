import { Counter } from 'prom-client'

import { Properties } from '@posthog/plugin-scaffold'

import { TopicMessage } from '~/kafka/producer'

import { defaultConfig } from '../../config/config'
import { KAFKA_PERSON } from '../../config/kafka-topics'
import { BasePerson, ClickHousePerson, InternalPerson, RawPerson, TimestampFormat } from '../../types'
import { logger } from '../../utils/logger'
import { castTimestampOrNow } from '../../utils/utils'
import { eventToPersonProperties } from '../../worker/ingestion/persons/person-property-utils'
import { captureException } from '../posthog'

export function unparsePersonPartial(person: Partial<InternalPerson>): Partial<RawPerson> {
    return {
        ...(person as BasePerson),
        ...(person.created_at ? { created_at: person.created_at.toISO() ?? undefined } : {}),
    }
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
    sendException = true,
    reportMetric?: () => void
): NodeJS.Timeout {
    return setTimeout(() => {
        const ctx = typeof context === 'function' ? context() : context
        logger.warn('⌛', message, ctx)
        if (sendException) {
            captureException(message, ctx ? { extra: ctx } : undefined)
        }
        if (reportMetric) {
            reportMetric()
        }
    }, timeout)
}

// Pre-computed mapping from property key to its $initial_ version
// This avoids string manipulation in the hot path
const INITIAL_KEY_MAP: Map<string, string> = new Map(
    Array.from(eventToPersonProperties, (key) => [key, `$initial_${key.replace('$', '')}`])
)

/** If we get new UTM params, make sure we set those  **/
export function personInitialAndUTMProperties(properties: Properties): Properties {
    // Instead of iterating all properties (could be 50+), iterate the known set (16 keys)
    // and check if each exists in properties - O(16) instead of O(n)
    let $set: Record<string, any> | undefined
    let $set_once: Record<string, any> | undefined

    for (const key of eventToPersonProperties) {
        if (!(key in properties)) {
            continue
        }

        const value = properties[key]

        if ($set === undefined) {
            // Handle malformed $set/$set_once (e.g. string instead of object)
            const existingSet = properties.$set
            const existingSetOnce = properties.$set_once
            $set = typeof existingSet === 'object' && existingSet !== null ? existingSet : {}
            $set_once = typeof existingSetOnce === 'object' && existingSetOnce !== null ? existingSetOnce : {}
        }

        if (!(key in $set!)) {
            $set![key] = value
        }

        // Use pre-computed initial key instead of string manipulation
        const initialKey = INITIAL_KEY_MAP.get(key)!
        if (!(initialKey in $set_once!)) {
            $set_once![initialKey] = value
        }
    }

    // Fast path: no person properties found
    if ($set === undefined) {
        return properties
    }

    // For the purposes of $initial properties, $os_name is treated as a fallback alias of $os, starting August 2024
    // It's a special case due to _some_ SDKs using $os_name: https://github.com/PostHog/posthog-js-lite/issues/244
    const osName = properties.$os_name
    if (osName !== undefined) {
        if (!('$os' in properties)) {
            properties.$os = osName
        }
        if (!('$os' in $set)) {
            $set.$os = osName
        }
        if (!('$initial_os' in $set_once!)) {
            $set_once!.$initial_os = osName
        }
        // $os_name is normalized to $os, so remove it from person properties
        delete $set.$os_name
        delete $set_once!.$initial_os_name
    }

    // Mutate in place instead of spreading entire properties object
    properties.$set = $set
    properties.$set_once = $set_once

    return properties
}

export function generateKafkaPersonUpdateMessage(person: InternalPerson, isDeleted = false): TopicMessage {
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

export function sanitizeString(value: string) {
    return value.replace(/\u0000/g, '\uFFFD')
}

export const surrogatesSubstitutedCounter = new Counter({
    name: 'surrogates_substituted_total',
    help: 'Stray UTF16 surrogates detected and removed from user input.',
})
