import { DateTime } from 'luxon'
import { Summary } from 'prom-client'
import { gunzip, gzip } from 'zlib'

import { parseJSON } from '~/common/utils/json-parse'
import { sanitizeForUTF8 } from '~/common/utils/strings'
import { UUIDT, castTimestampOrNow, clickHouseTimestampToDateTime } from '~/common/utils/utils'

import { ClickHouseTimestamp, ISOTimestamp, RawClickHouseEvent, Team, TimestampFormat } from '../types'
import { CdpInternalEvent } from './schema'
import { HogFunctionInvocationGlobals, HogFunctionType, LogEntry, LogEntrySerialized, MinimalLogEntry } from './types'

// ID of functions that are hidden from normal users and used by us for special testing
// For example, transformations use this to only run if in comparison mode
export const CDP_TEST_ID = '[CDP-TEST-HIDDEN]'
export const MAX_LOG_LENGTH = 10000
const TRUNCATION_SUFFIX = '... (truncated)'
const REDACTED = '***REDACTED***'

// Sync with person.py and constants.tsx
export const PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES = ['email', 'name', 'username']

export const getPersonDisplayName = (team: Team, distinctId: string, properties: Record<string, any>): string => {
    const personDisplayNameProperties = team.person_display_name_properties ?? PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
    const customPropertyKey = personDisplayNameProperties.find((x) => properties?.[x])
    const propertyIdentifier = customPropertyKey ? properties[customPropertyKey] : undefined

    const customIdentifier: string =
        typeof propertyIdentifier !== 'string' ? JSON.stringify(propertyIdentifier) : propertyIdentifier

    return (customIdentifier || String(distinctId))?.trim()
}

// TRICKY: the timestamp can be an ISO one, for example when it comes from the test api, so both
// formats are accepted. Returns null rather than throwing, because a test-invocation body can carry
// a `clickhouse_event` that is not an event at all, such as the `{}` a caller sends for an optional
// field it has no value for.
export function parseClickHouseEventTimestamp(timestamp: unknown): ISOTimestamp | null {
    if (typeof timestamp !== 'string') {
        return null
    }
    if (DateTime.fromISO(timestamp).isValid) {
        return timestamp as ISOTimestamp
    }
    const parsed = clickHouseTimestampToDateTime(timestamp as ClickHouseTimestamp)
    return parsed.isValid ? (parsed.toISO() as ISOTimestamp) : null
}

export function isConvertibleClickHouseEvent(event: unknown): event is RawClickHouseEvent {
    return (
        !!event &&
        typeof event === 'object' &&
        parseClickHouseEventTimestamp((event as RawClickHouseEvent).timestamp) !== null
    )
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

    const eventTimestamp = parseClickHouseEventTimestamp(event.timestamp)!
    const eventCapturedAt = parseClickHouseEventTimestamp(event.captured_at)

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
            captured_at: eventCapturedAt,
            url: `${projectUrl}/events/${encodeURIComponent(event.uuid)}/${encodeURIComponent(eventTimestamp)}`,
        },
        person,
    }

    return context
}

export function convertBatchHogFlowRequestToHogFunctionInvocationGlobals({
    team,
    personId,
    siteUrl,
}: {
    team: Team
    personId: string
    siteUrl: string
}): HogFunctionInvocationGlobals {
    const projectUrl = `${siteUrl}/project/${team.id}`

    const person: HogFunctionInvocationGlobals['person'] = {
        id: personId,
        properties: {},
        name: '',
        url: `${projectUrl}/person/${encodeURIComponent(personId)}`,
    }

    const context: HogFunctionInvocationGlobals = {
        project: {
            id: team.id,
            name: team.name,
            url: projectUrl,
        },
        event: {
            event: '$batch_hog_flow_invocation',
            properties: {},
            uuid: new UUIDT().toString(),
            distinct_id: '', // Not applicable for batch processing but left here for compatibility
            elements_chain: '',
            timestamp: DateTime.now().toISO(),
            url: '',
        },
        person,
    }

    return context
}

export function convertAccountBatchHogFlowRequestToHogFunctionInvocationGlobals({
    team,
    externalId,
    groupType,
    siteUrl,
}: {
    team: Team
    externalId: string
    groupType: string
    siteUrl: string
}): HogFunctionInvocationGlobals {
    const projectUrl = `${siteUrl}/project/${team.id}`

    const context: HogFunctionInvocationGlobals = {
        project: {
            id: team.id,
            name: team.name,
            url: projectUrl,
        },
        event: {
            event: '$batch_hog_flow_invocation',
            // $groups drives the worker's group hydration, so account actions defaulting to
            // {groups.<type>.id} resolve without any account-specific plumbing.
            properties: { $groups: { [groupType]: externalId } },
            uuid: new UUIDT().toString(),
            // The account's group key doubles as the invocation's distinct_id so
            // invocation_results are filterable per account. Account runs carry no person;
            // the hogflow worker skips person resolution for account audiences.
            distinct_id: externalId,
            elements_chain: '',
            timestamp: DateTime.now().toISO(),
            url: '',
        },
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
        properties = { ...properties.exception_props, ...properties }
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
            captured_at: null, // Not applicable for internal events
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
    return [
        '$error_tracking_issue_created',
        '$error_tracking_issue_reopened',
        '$error_tracking_issue_spiking',
    ].includes(event.event)
}

export function filterExists<T>(value: T): value is NonNullable<T> {
    return Boolean(value)
}

// Keys whose value is a credential however the request built it, for example a Basic `Authorization`
// header that a destination derives from an API key. No collected input value matches a derived value.
const LOGGED_CREDENTIAL_KEY =
    /authorization|cookie|token|secret|password|passcode|credential|api[-_]?key|private[-_]?key|signing[-_]?key/i

// Header names that carry a credential. Matched against the keys of a dictionary input, so a
// free-form headers map still gets its credential masked without the whole map being treated as
// secret (which would hide ordinary headers like Content-Type from the person configuring it).
const CREDENTIAL_HEADER_NAMES =
    /^(authorization|proxy-authorization|cookie|x-api-key|api-?key|x-auth-token|auth-?token|access-?token|x-auth|token|secret|x-secret)$/i

/**
 * Every configured secret for a hog function, so callers can mask them out of anything they surface.
 *
 * A destination's error text is not safe just because we wrote the format string: it routinely
 * embeds the third party's response body, and an API that rejects a credential tends to quote the
 * credential back. Anything built from a response body has to go through `redactSensitiveValues`
 * with this list before it reaches a log, an error, or ClickHouse.
 */
export const getSensitiveValues = (hogFunction: HogFunctionType, inputs: Record<string, any>): string[] => {
    const values: string[] = []

    const collectStringValues = (obj: any, depth = 0): void => {
        // The depth limit stops a self-referencing object from recursing forever.
        if (!obj || typeof obj !== 'object' || depth > 10) {
            return
        }
        // Assume the values are the sensitive parts. Some integrations nest them, for example a
        // Google Cloud key file under `key_info`, so nested objects and arrays are collected too.
        Object.values(obj).forEach((val: any) => {
            if (typeof val === 'string') {
                values.push(val)
            } else {
                collectStringValues(val, depth + 1)
            }
        })
    }

    // A webhook's `headers` is free-form, so it is not marked secret, but it is where a credential
    // most often sits — and a webhook whose credential is rejected is exactly the case that gets it
    // quoted back. Mask values under header names that carry one, whatever the secret flag says.
    const collectCredentialHeaders = (obj: any): void => {
        if (!obj || typeof obj !== 'object') {
            return
        }
        Object.entries(obj).forEach(([key, val]) => {
            if (typeof val !== 'string' || !CREDENTIAL_HEADER_NAMES.test(key.trim())) {
                return
            }
            values.push(val)
            // Sent as "Bearer abc" but usually quoted back as bare "abc", so mask both forms.
            const withoutScheme = val.replace(/^(bearer|basic|token)\s+/i, '')
            if (withoutScheme !== val) {
                values.push(withoutScheme)
            }
        })
    }

    hogFunction.inputs_schema?.forEach((schema) => {
        if (schema.type === 'dictionary' && !schema.secret) {
            collectCredentialHeaders(inputs[schema.key])
        }
        // A function keeps the schema it was saved with, so a credential input that a later template
        // version marks secret is still `secret: false` on older functions.
        if (
            schema.secret ||
            LOGGED_CREDENTIAL_KEY.test(schema.key) ||
            schema.type === 'integration' ||
            schema.type === 'integration_multi' ||
            schema.type === 'push_subscription'
        ) {
            const value = inputs[schema.key]
            if (typeof value === 'string') {
                values.push(value)
            } else if (schema.type === 'integration_multi' && Array.isArray(value)) {
                // integration_multi resolves to an array of integration objects, each carrying its own
                // sensitive_config (e.g. APNs signing_key, FCM access_token_raw) — mask every one.
                value.forEach((item) => collectStringValues(item))
            } else if (
                (schema.type === 'dictionary' ||
                    schema.type === 'integration' ||
                    schema.type === 'push_subscription') &&
                typeof value === 'object'
            ) {
                collectStringValues(value)
            }
        }
    })

    // We don't want to add "REDACTED" for empty strings
    return values.filter((v) => v.trim())
}

export const redactSensitiveValues = (message: string, sensitiveValues?: string[]): string => {
    // Callers pass `err.message` straight from a catch, where `err` is `any` and need not be an
    // Error at all, so a non-string reaches this despite the signature. Hand it back untouched
    // rather than throwing inside the code path that is reporting someone else's failure.
    if (!message || typeof message !== 'string' || !sensitiveValues?.length) {
        return message
    }

    const variants = new Set<string>()
    sensitiveValues.forEach((sensitiveValue) => {
        if (typeof sensitiveValue !== 'string' || !sensitiveValue) {
            return
        }
        variants.add(sensitiveValue)
        // Logged objects are JSON-encoded, which escapes quotes, backslashes and newlines, so a secret
        // such as a PEM private key no longer matches its raw form inside the message.
        variants.add(JSON.stringify(sensitiveValue).slice(1, -1))
    })
    if (!variants.size) {
        return message
    }

    // Replace every value in one pass over the original text, longest first. Replacing the values one
    // after another rescans the markers that earlier passes inserted, so a value that occurs inside
    // the marker, such as `*`, multiplies the message length on every pass.
    const pattern = new RegExp(
        [...variants]
            .sort((a, b) => b.length - a.length)
            .map((variant) => variant.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
            .join('|'),
        'g'
    )
    return message.replace(pattern, REDACTED)
}

// Redacts each string before the outer JSON encoding. A value that is already a JSON string, such as a
// request body, is otherwise escaped a second time and no longer matches the escaped secret.
const serializeRedactedLogArg = (arg: unknown, sensitiveValues: string[]): unknown => {
    if (typeof arg === 'string') {
        return arg
    }
    return JSON.stringify(arg, (key, value) => {
        if (typeof value !== 'string') {
            return value
        }
        return key && LOGGED_CREDENTIAL_KEY.test(key) ? REDACTED : redactSensitiveValues(value, sensitiveValues)
    })
}

// Masks secrets in a caught error but keeps the error itself, so `instanceof` retry checks and
// `String(error)` behave as before.
export const redactError = (error: any, sensitiveValues: string[]): any => {
    if (typeof error === 'string') {
        return redactSensitiveValues(error, sensitiveValues)
    }
    if (error instanceof Error) {
        const message = redactSensitiveValues(error.message, sensitiveValues)
        try {
            error.message = message
        } catch {
            return new Error(message)
        }
    }
    return error
}

export const sanitizeLogMessage = (args: any[], sensitiveValues?: string[], maxLength = MAX_LOG_LENGTH): string => {
    let message = redactSensitiveValues(
        args.map((arg) => (typeof arg !== 'string' ? JSON.stringify(arg) : arg)).join(', '),
        sensitiveValues
    )

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

export const createAddLogFunction = (logs: MinimalLogEntry[], sensitiveValues?: string[]) => {
    return (level: 'debug' | 'warn' | 'error' | 'info', ...args: any[]) => {
        const logArgs = sensitiveValues ? args.map((arg) => serializeRedactedLogArg(arg, sensitiveValues)) : args
        logs.push({
            level,
            timestamp: DateTime.now(),
            message: sanitizeLogMessage(logArgs, sensitiveValues),
        })
    }
}

export const destinationE2eLagMsSummary = new Summary({
    name: 'destination_e2e_lag_ms',
    help: 'Time difference in ms between event capture time and destination finishing time',
    percentiles: [0.5, 0.9, 0.95, 0.99],
})
