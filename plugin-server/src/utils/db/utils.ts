import { Counter } from 'prom-client'

import { Properties } from '@posthog/plugin-scaffold'

import { TopicMessage } from '~/kafka/producer'

import { defaultConfig } from '../../config/config'
import { KAFKA_PERSON } from '../../config/kafka-topics'
import {
    BasePerson,
    ClickHousePerson,
    InternalPerson,
    PluginLogEntryType,
    PluginLogLevel,
    RawPerson,
    TimestampFormat,
} from '../../types'
import { logger } from '../../utils/logger'
import { areMapsEqual, castTimestampOrNow } from '../../utils/utils'
import {
    eventToPersonProperties,
    initialCampaignParams,
    initialEventToPersonProperties,
} from '../../worker/ingestion/persons/person-property-utils'
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
        propertiesCopy.$set = { ...Object.fromEntries(maybeSet), ...(properties.$set || {}) }
    }
    if (maybeSetOnce.length > 0) {
        propertiesCopy.$set_once = { ...Object.fromEntries(maybeSetOnce), ...(properties.$set_once || {}) }
    }

    if (propertiesCopy.$os_name) {
        // For the purposes of $initial properties, $os_name is treated as a fallback alias of $os, starting August 2024
        // It's as special case due to _some_ SDKs using $os_name: https://github.com/PostHog/posthog-js-lite/issues/244
        propertiesCopy.$os ??= propertiesCopy.$os_name
        propertiesCopy.$set.$os ??= propertiesCopy.$os_name
        propertiesCopy.$set_once.$initial_os ??= propertiesCopy.$os_name
        // Make sure $os_name is not used in $set/$set_once, as that hasn't been a thing before
        delete propertiesCopy.$set.$os_name
        delete propertiesCopy.$set_once.$initial_os_name
    }

    return propertiesCopy
}

export function hasDifferenceWithProposedNewNormalisationMode(properties: Properties): boolean {
    // this functions checks if there would be a difference in the properties if we strip the initial campaign params
    // when any $set_once initial eventToPersonProperties are present. This will often return true for events from
    // posthog-js, but it is unknown if this will be the case for other SDKs.
    if (
        !properties.$set_once ||
        !Object.keys(properties.$set_once).some((key) => initialEventToPersonProperties.has(key))
    ) {
        return false
    }

    const propertiesForPerson: [string, any][] = Object.entries(properties).filter(([key]) =>
        eventToPersonProperties.has(key)
    )

    const maybeSetOnce: [string, any][] = propertiesForPerson.map(([key, value]) => [
        `$initial_${key.replace('$', '')}`,
        value,
    ])

    if (maybeSetOnce.length === 0) {
        return false
    }

    const filteredMayBeSetOnce = maybeSetOnce.filter(([key]) => !initialCampaignParams.has(key))

    const setOnce = new Map(Object.entries({ ...Object.fromEntries(maybeSetOnce), ...(properties.$set_once || {}) }))
    const filteredSetOnce = new Map(
        Object.entries({ ...Object.fromEntries(filteredMayBeSetOnce), ...(properties.$set_once || {}) })
    )

    return !areMapsEqual(setOnce, filteredSetOnce)
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

export function sanitizeString(value: string) {
    return value.replace(/\u0000/g, '\uFFFD')
}

export const surrogatesSubstitutedCounter = new Counter({
    name: 'surrogates_substituted_total',
    help: 'Stray UTF16 surrogates detected and removed from user input.',
})
