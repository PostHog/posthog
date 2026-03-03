import { Message } from 'node-rdkafka'

import { sanitizeEvent } from '~/utils/event'

import { IncomingEvent, PipelineEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { UUID } from '../../utils/utils'
import { dlq, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

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
            const event: PipelineEvent = sanitizeEvent(parsePipelineEvent(combinedEvent))

            return Promise.resolve(ok({ ...input, event: { event } }))
        } catch (error) {
            logger.warn('Failed to parse Kafka message', { error })
            return Promise.resolve(
                dlq('failed_parse_message', error instanceof Error ? error : new Error(String(error)))
            )
        }
    }
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
