// NOTE: PostIngestionEvent is our context event - it should never be sent directly to an output, but rather transformed into a lightweight schema
import { DateTime } from 'luxon'
import { gunzip, gzip } from 'zlib'

import { sanitizeForUTF8 } from '~/utils/strings'

import { RawClickHouseEvent, Team, TimestampFormat } from '../types'
import { parseJSON } from '../utils/json-parse'
import { castTimestampOrNow, clickHouseTimestampToISO } from '../utils/utils'
import { CdpInternalEvent } from './schema'
import { HogFunctionInvocationGlobals, HogFunctionType, LogEntry, LogEntrySerialized, MinimalLogEntry } from './types'

// ID of functions that are hidden from normal users and used by us for special testing
// For example, transformations use this to only run if in comparison mode
export const CDP_TEST_ID = '[CDP-TEST-HIDDEN]'
export const MAX_LOG_LENGTH = 10000
const TRUNCATION_SUFFIX = '... (truncated)'

export const PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES = [
    'email',
    'Email',
    'name',
    'Name',
    'username',
    'Username',
    'UserName',
]

export const getPersonDisplayName = (team: Team, distinctId: string, properties: Record<string, any>): string => {
    const personDisplayNameProperties = team.person_display_name_properties ?? PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
    const customPropertyKey = personDisplayNameProperties.find((x) => properties?.[x])
    const propertyIdentifier = customPropertyKey ? properties[customPropertyKey] : undefined

    const customIdentifier: string =
        typeof propertyIdentifier !== 'string' ? JSON.stringify(propertyIdentifier) : propertyIdentifier

    return (customIdentifier || String(distinctId))?.trim()
}

// that we can keep to as a contract
export function convertToHogFunctionInvocationGlobals(
    event: RawClickHouseEvent,
    team: Team,
    siteUrl: string
): HogFunctionInvocationGlobals {
    const properties = event.properties ? parseJSON(event.properties) : {}
    const projectUrl = `${siteUrl}/project/${team.id}`

    let person: HogFunctionInvocationGlobals['person']

    if (event.person_id) {
        const personProperties = event.person_properties ? parseJSON(event.person_properties) : {}
        const personDisplayName = getPersonDisplayName(team, event.distinct_id, personProperties)

        person = {
            id: event.person_id,
            properties: personProperties,
            name: personDisplayName,
            url: `${projectUrl}/person/${encodeURIComponent(event.distinct_id)}`,
        }
    }

    // TRICKY: the timsestamp can sometimes be an ISO for example if coming from the test api
    // so we need to handle that case
    const eventTimestamp = DateTime.fromISO(event.timestamp).isValid
        ? event.timestamp
        : clickHouseTimestampToISO(event.timestamp)

    const context: HogFunctionInvocationGlobals = {
        project: {
            id: team.id,
            name: team.name,
            url: projectUrl,
        },
        event: {
            uuid: event.uuid,
            event: event.event!,
            elements_chain: event.elements_chain,
            distinct_id: event.distinct_id,
            properties,
            timestamp: eventTimestamp,
            url: `${projectUrl}/events/${encodeURIComponent(event.uuid)}/${encodeURIComponent(eventTimestamp)}`,
        },
        person,
    }

    return context
}

export function convertInternalEventToHogFunctionInvocationGlobals(
    data: CdpInternalEvent,
    team: Team,
    siteUrl: string
): HogFunctionInvocationGlobals {
    const projectUrl = `${siteUrl}/project/${team.id}`

    let person: HogFunctionInvocationGlobals['person']

    if (data.person) {
        const personDisplayName = getPersonDisplayName(team, data.event.distinct_id, data.person.properties)

        person = {
            id: data.person.id,
            properties: data.person.properties,
            name: personDisplayName,
            url: data.person.url ?? '',
        }
    }

    let properties = data.event.properties

    // KLUDGE: spread the properties of the exception event that caused the internal issue event
    // so those properties can be used to filter CDP destinations for error tracking alerts
    if (
        isInternalErrorTrackingEvent(data.event) &&
        'exception_props' in properties &&
        typeof properties.exception_props === 'object'
    ) {
        properties = { ...properties, ...properties.exception_props }
        delete properties.exception_props
    }

    const context: HogFunctionInvocationGlobals = {
        project: {
            id: team.id,
            name: team.name,
            url: projectUrl,
        },
        event: {
            uuid: data.event.uuid,
            event: data.event.event,
            elements_chain: '', // Not applicable but left here for compatibility
            distinct_id: data.event.distinct_id,
            properties: properties,
            timestamp: data.event.timestamp,
            url: data.event.url ?? '',
        },
        person,
    }

    return context
}

export const gzipObject = async <T extends object>(object: T): Promise<string> => {
    const payload = JSON.stringify(object)
    const buffer = await new Promise<Buffer>((res, rej) =>
        gzip(payload, (err, result) => (err ? rej(err) : res(result)))
    )
    const res = buffer.toString('base64')

    // NOTE: Base64 encoding isn't as efficient but we would need to change the kafka producer/consumers to use ucs2 or something
    // as well in order to support binary data better

    return res
}

export const unGzipObject = async <T extends object>(data: string): Promise<T> => {
    const res = await new Promise<Buffer>((res, rej) =>
        gunzip(Buffer.from(data, 'base64'), (err, result) => (err ? rej(err) : res(result)))
    )

    return parseJSON(res.toString())
}

export const fixLogDeduplication = (logs: LogEntry[]): LogEntrySerialized[] => {
    const preparedLogs: LogEntrySerialized[] = []
    const sortedLogs = logs.sort((a, b) => a.timestamp.toMillis() - b.timestamp.toMillis())

    if (sortedLogs.length === 0) {
        return []
    }

    // Start with a timestamp that is guaranteed to be before the first log entry
    let previousTimestamp = sortedLogs[0].timestamp.minus(1)

    sortedLogs.forEach((logEntry) => {
        // TRICKY: The clickhouse table dedupes logs with the same timestamp - we need to ensure they are unique by simply plus-ing 1ms
        // if the timestamp is the same as the previous one
        if (logEntry.timestamp <= previousTimestamp) {
            logEntry.timestamp = previousTimestamp.plus(1)
        }

        previousTimestamp = logEntry.timestamp

        const sanitized: LogEntrySerialized = {
            ...logEntry,
            timestamp: castTimestampOrNow(logEntry.timestamp, TimestampFormat.ClickHouse),
        }
        preparedLogs.push(sanitized)
    })

    return preparedLogs
}

export function isLegacyPluginHogFunction(hogFunction: Pick<HogFunctionType, 'template_id'>): boolean {
    return hogFunction.template_id?.startsWith('plugin-') ?? false
}

export function isSegmentPluginHogFunction(hogFunction: Pick<HogFunctionType, 'template_id'>): boolean {
    return hogFunction.template_id?.startsWith('segment-') ?? false
}

export function isNativeHogFunction(hogFunction: Pick<HogFunctionType, 'template_id'>): boolean {
    return hogFunction.template_id?.startsWith('native-') ?? false
}

export function isInternalErrorTrackingEvent(event: CdpInternalEvent['event']): boolean {
    return ['$error_tracking_issue_created', '$error_tracking_issue_reopened'].includes(event.event)
}

export function filterExists<T>(value: T): value is NonNullable<T> {
    return Boolean(value)
}

export const sanitizeLogMessage = (args: any[], sensitiveValues?: string[], maxLength = MAX_LOG_LENGTH): string => {
    let message = args.map((arg) => (typeof arg !== 'string' ? JSON.stringify(arg) : arg)).join(', ')

    // Find and replace any sensitive values
    sensitiveValues?.forEach((sensitiveValue) => {
        message = message.replaceAll(sensitiveValue, '***REDACTED***')
    })

    let truncateAt = maxLength

    // Check if we're in the middle of a surrogate pair
    if (truncateAt > 0 && truncateAt < message.length + TRUNCATION_SUFFIX.length) {
        const charAtTruncate = message.charCodeAt(truncateAt)
        const charBeforeTruncate = message.charCodeAt(truncateAt - 1)

        // If we're about to cut after a high surrogate or before a low surrogate
        if ((charBeforeTruncate & 0xfc00) === 0xd800 || (charAtTruncate & 0xfc00) === 0xdc00) {
            // Move back to avoid cutting through the surrogate pair
            truncateAt--
            // If we moved back and are still at a high surrogate, move back one more
            if (truncateAt > 0 && (message.charCodeAt(truncateAt - 1) & 0xfc00) === 0xd800) {
                truncateAt--
            }
        }
        message = sanitizeForUTF8(message.slice(0, truncateAt) + TRUNCATION_SUFFIX)
    }

    return message
}

export const logEntry = (level: 'debug' | 'warn' | 'error' | 'info', ...args: any[]) => {
    return {
        level,
        timestamp: DateTime.now(),
        message: sanitizeLogMessage(args),
    }
}

export const createAddLogFunction = (logs: MinimalLogEntry[]) => {
    return (level: 'debug' | 'warn' | 'error' | 'info', ...args: any[]) => {
        logs.push({
            level,
            timestamp: DateTime.now(),
            message: sanitizeLogMessage(args),
        })
    }
}
