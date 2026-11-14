import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { sanitizeEvent } from '~/common/utils/event'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { UUID } from '~/common/utils/utils'
import { TopHogMetricFactory, count, max, sum, timer } from '~/ingestion/framework/extensions/tophog'
import { dlq, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { Properties } from '~/plugin-scaffold'
import { EventHeaders, IncomingEvent, PipelineEvent } from '~/types'

export const v1OptionsAppliedTotal = new Counter({
    name: 'ingestion_v1_options_applied_total',
    help: 'Capture v1 outbound options applied to event properties, by option key, outcome, and whether capture also spliced them into the properties',
    labelNames: ['key', 'outcome', 'splice'],
})

/** Capture v1 sets this Kafka header only while it also splices the option values into the properties. */
const LEGACY_PROPERTY_SPLICE_HEADER = 'legacy_property_splice'

/** Capture v1 option keys that always override the matching client property. The key names are the capture contract. */
const CAPTURE_OPTION_OVERRIDES: ReadonlyArray<[key: string, property: string, type: 'string' | 'boolean']> = [
    ['session_id', '$session_id', 'string'],
    ['window_id', '$window_id', 'string'],
    ['cookieless_mode', '$cookieless_mode', 'boolean'],
    ['disable_skew_correction', '$ignore_sent_at', 'boolean'],
    ['product_tour_id', '$product_tour_id', 'string'],
    ['process_person_profile', '$process_person_profile', 'boolean'],
]

/**
 * TopHog metrics for the parse step: parse timing and raw message sizes,
 * keyed by token (the team is not resolved yet at parse time). Sizes are
 * recorded from the raw Kafka message, so malformed events that DLQ at parse
 * still show up — this is the earliest per-sender visibility the pipeline
 * has. Wire via `.parseMessage({ wrap: (step) => topHog(step, parseMessageTopHogMetrics()) })`.
 */
export function parseMessageTopHogMetrics<
    TInput extends { message: Message; headers: EventHeaders },
    TOutput,
>(): TopHogMetricFactory<TInput, TOutput>[] {
    const byToken = (input: TInput) => ({ token: input.headers.token ?? 'unknown' })
    const messageBytes = (input: TInput) => input.message.value?.length ?? 0
    return [
        count('messages_by_token', byToken),
        timer('parse_time_ms_by_token', byToken),
        sum('message_size_by_token', byToken, messageBytes),
        max('max_message_size_by_token', byToken, messageBytes),
        sum(
            'message_size_by_token_per_partition',
            (input) => ({ ...byToken(input), partition: String(input.message.partition) }),
            messageBytes
        ),
    ]
}

export function createParseKafkaMessageStep<T extends { message: Message }>(): ProcessingStep<
    T,
    T & { event: IncomingEvent }
> {
    return function parseKafkaMessageStep(input) {
        const { message } = input

        try {
            const {
                data: dataStr,
                token: _token,
                options,
                ...rawEvent
            } = requireObject(parseJSON(message.value!.toString()), 'outer message')
            const data = requireObject(parseJSON(requireString(dataStr, 'data')), 'data field')
            const combinedEvent: Record<string, unknown> = { ...data, ...rawEvent }

            if (!combinedEvent.uuid || !UUID.validateString(combinedEvent.uuid, false)) {
                const cause = combinedEvent.uuid ? 'invalid_uuid' : 'empty_uuid'
                return Promise.resolve(dlq(cause))
            }

            // Use sanitize-only normalization here. Full normalization (including
            // personInitialAndUTMProperties) happens after transformations in normalizeEventStep.
            const parsed = parsePipelineEvent(combinedEvent)
            applyCaptureOptions(options, parsed.properties!, message.headers)
            const event: PipelineEvent = sanitizeEvent(parsed)

            return Promise.resolve(ok({ ...input, event: { event } }))
        } catch (error) {
            logger.warn('Failed to parse Kafka message', { error })
            return Promise.resolve(
                dlq('failed_parse_message', error instanceof Error ? error : new Error(String(error)))
            )
        }
    }
}

/**
 * Applies the server-side values that capture v1 publishes in the outer message's `options`.
 * Only the outer message is read: `data` is client-controlled, and `/i/v0/ai` puts the whole client event there.
 */
function applyCaptureOptions(options: unknown, properties: Properties, headers: Message['headers']): void {
    if (options === undefined) {
        return
    }
    const splice = headers?.some((header) => header[LEGACY_PROPERTY_SPLICE_HEADER]?.toString() === 'true')
        ? 'on'
        : 'off'
    const count = (key: string, outcome: string): void => {
        v1OptionsAppliedTotal.labels({ key, outcome, splice }).inc()
    }
    if (typeof options !== 'object' || options === null || Array.isArray(options)) {
        count('options', 'invalid_type')
        return
    }
    const values = options as Record<string, unknown>

    for (const [key, property, type] of CAPTURE_OPTION_OVERRIDES) {
        if (!Object.hasOwn(values, key)) {
            continue
        }
        const value = values[key]
        if (typeof value !== type) {
            count(key, 'invalid_type')
            continue
        }
        const current = properties[property]
        count(key, current == null ? 'filled' : current === value ? 'same' : 'overridden')
        properties[property] = value
    }

    if (!Object.hasOwn(values, 'req_lib') && !Object.hasOwn(values, 'req_lib_version')) {
        return
    }
    const lib = values.req_lib
    const libVersion = values.req_lib_version
    if (typeof lib !== 'string' || typeof libVersion !== 'string') {
        count('req_lib', 'invalid_type')
        return
    }
    if (lib.trim() === '' || libVersion.trim() === '') {
        count('req_lib', 'empty')
        return
    }
    if (!isNonEmptyString(properties.$lib)) {
        properties.$lib = lib
        properties.$lib_version = libVersion
        count('req_lib', 'filled')
    } else if (properties.$lib !== lib) {
        count('req_lib', 'kept')
    } else if (!isNonEmptyString(properties.$lib_version)) {
        properties.$lib_version = libVersion
        count('req_lib', 'version_filled')
    } else {
        count('req_lib', properties.$lib_version === libVersion ? 'same' : 'kept')
    }
}

function isNonEmptyString(value: unknown): value is string {
    return typeof value === 'string' && value !== ''
}

function parsePipelineEvent(raw: Record<string, unknown>): PipelineEvent {
    return {
        uuid: requireString(raw.uuid, 'uuid'),
        distinct_id: requireString(raw.distinct_id, 'distinct_id'),
        event: requireString(raw.event, 'event'),
        ip: optionalString(raw.ip, 'ip', null),
        site_url: optionalString(raw.site_url, 'site_url', ''),
        now: optionalString(raw.now, 'now', ''),
        properties: optionalObject(raw.properties, 'properties') ?? {},
        team_id: optionalNumber(raw.team_id, 'team_id'),
        sent_at: optionalString(raw.sent_at, 'sent_at'),
        timestamp: optionalString(raw.timestamp, 'timestamp'),
        offset: optionalNumber(raw.offset, 'offset'),
        $set: optionalObject(raw.$set, '$set'),
        $set_once: optionalObject(raw.$set_once, '$set_once'),
    }
}

function requireString(value: unknown, field: string): string {
    if (typeof value === 'string') {
        return value
    }
    if (typeof value === 'number' || typeof value === 'boolean') {
        return String(value)
    }
    throw new Error(`expected string for ${field}, got ${typeof value}`)
}

function optionalString(value: unknown, field: string): string | undefined
function optionalString(value: unknown, field: string, fallback: string): string
function optionalString(value: unknown, field: string, fallback: null): string | null
function optionalString(value: unknown, field: string, fallback?: string | null): string | null | undefined {
    if (value == null) {
        return fallback
    }
    return requireString(value, field)
}

function requireNumber(value: unknown, field: string): number {
    if (typeof value === 'string') {
        const parsed = Number(value)
        if (!Number.isFinite(parsed)) {
            throw new Error(`expected number for ${field}, got non-numeric string`)
        }
        return parsed
    }
    if (typeof value !== 'number') {
        throw new Error(`expected number for ${field}, got ${typeof value}`)
    }
    return value
}

function optionalNumber(value: unknown, field: string): number | undefined {
    return value == null ? undefined : requireNumber(value, field)
}

function requireObject(value: unknown, field: string): Record<string, unknown> {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
        throw new Error(`expected object for ${field}, got ${Array.isArray(value) ? 'array' : typeof value}`)
    }
    return value as Record<string, unknown>
}

function optionalObject(value: unknown, field: string): Record<string, any> | undefined {
    return value == null ? undefined : requireObject(value, field)
}
