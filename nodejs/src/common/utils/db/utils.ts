import { Counter } from 'prom-client'

import { PERSONS_OUTPUT } from '~/common/outputs'
import { PersonMessage } from '~/common/persons/person-message'
import { eventToPersonProperties } from '~/common/persons/person-property-utils'
import { Properties } from '~/plugin-scaffold'
import { BasePerson, InternalPerson, RawPerson, TimestampFormat } from '~/types'

import { defaultConfig } from '../../config/config'
import { logger } from '../../utils/logger'
import { castTimestampOrNow } from '../../utils/utils'
import { captureException } from '../posthog'

export function unparsePersonPartial(person: Partial<InternalPerson>): Partial<RawPerson> {
    return {
        ...(person as BasePerson),
        ...(person.created_at ? { created_at: person.created_at.toISO() ?? undefined } : {}),
        ...(person.last_seen_at !== undefined ? { last_seen_at: person.last_seen_at?.toISO() ?? null } : {}),
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

    // Server-side SDKs set $is_server: true. Don't lift their host $os/$os_version onto the person
    // (it poisons the sticky $initial_os). Client events omit $is_server (or set it false).
    const skipServerHostOs = properties.$is_server === true

    for (const key of eventToPersonProperties) {
        if (!(key in properties)) {
            continue
        }

        if (skipServerHostOs && (key === '$os' || key === '$os_version')) {
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
        // Never write a null into $set_once: browser SDKs send every absent campaign param as an
        // explicit null, and $set_once only applies while the person property is missing, so
        // `$initial_gclid: null` would permanently block the real first-touch value. $set keeps
        // its nulls because clearing the latest-touch value on a param-less visit is intentional.
        if (value != null && !(initialKey in $set_once!)) {
            $set_once![initialKey] = value
        }
    }

    // Fast path: no person properties found
    if ($set === undefined) {
        return properties
    }

    // For the purposes of $initial properties, $os_name is treated as a fallback alias of $os, starting August 2024
    // It's a special case due to _some_ SDKs using $os_name: https://github.com/PostHog/posthog-js-lite/issues/244
    // normalizeOsAlias fills the event's own $os upstream, so the loop above already lifted $os into $set.
    const osName = properties.$os_name
    if (osName !== undefined && !skipServerHostOs) {
        // Only reachable when $os is null, since the loop skips $initial_os for a null value; the
        // non-null check on $os_name is the same first-touch rule as above.
        if (osName !== null && !('$initial_os' in $set_once!)) {
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

// Deletion call sites own the version they emit (the +100 fudge for hard deletes,
// the exact stamped death version for tombstones), so a deletion must state it
// explicitly — a stale person.version can never become a no-headroom death row.
export function generateKafkaPersonUpdateMessage(person: InternalPerson, isDeleted?: false): PersonMessage
export function generateKafkaPersonUpdateMessage(
    person: InternalPerson,
    isDeleted: true,
    deletedVersion: number
): PersonMessage
export function generateKafkaPersonUpdateMessage(
    person: InternalPerson,
    isDeleted = false,
    deletedVersion?: number
): PersonMessage {
    return {
        output: PERSONS_OUTPUT,
        value: Buffer.from(
            JSON.stringify({
                id: person.uuid,
                created_at: castTimestampOrNow(person.created_at, TimestampFormat.ClickHouseSecondPrecision),
                properties: JSON.stringify(person.properties),
                team_id: person.team_id,
                is_identified: Number(person.is_identified),
                is_deleted: Number(isDeleted),
                version: isDeleted ? deletedVersion : person.version,
                last_seen_at: person.last_seen_at
                    ? castTimestampOrNow(person.last_seen_at, TimestampFormat.ClickHouseSecondPrecision)
                    : null,
            })
        ),
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
