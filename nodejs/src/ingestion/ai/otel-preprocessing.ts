/**
 * OTel preprocessing step for AI events.
 *
 * This module transforms `$ai_raw_data` events containing OTel payloads into individual
 * PostHog AI events (`$ai_generation`, `$ai_span`, etc.) during ingestion preprocessing.
 *
 * The Rust OTel endpoint sends events with:
 * - event: "$ai_raw_data"
 * - properties.format: "otel_trace"
 * - properties.data: { resourceSpans: [...] }
 *
 * This step extracts each span and produces individual AI events as side effects,
 * then drops the original container event.
 */
import { randomUUID } from 'crypto'

import { KAFKA_EVENTS_PLUGIN_INGESTION } from '../../config/kafka-topics'
import { KafkaProducerWrapper, MessageKey } from '../../kafka/producer'
import { PostTeamPreprocessingSubpipelineInput } from '../analytics/post-team-preprocessing-subpipeline'
import { drop, ok, PipelineResult } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

interface OtelSpan {
    traceId?: string
    spanId?: string
    parentSpanId?: string
    startTimeUnixNano?: string | number
    attributes?: Record<string, unknown>
}

interface OtelScopeSpans {
    spans?: OtelSpan[]
}

interface OtelResourceSpans {
    resource?: {
        attributes?: Record<string, unknown>
    }
    scopeSpans?: OtelScopeSpans[]
}

interface OtelTraceData {
    resourceSpans?: OtelResourceSpans[]
}

const ATTRIBUTE_MAP: Record<string, string> = {
    'gen_ai.input.messages': '$ai_input',
    'gen_ai.output.messages': '$ai_output_choices',
    'gen_ai.usage.input_tokens': '$ai_input_tokens',
    'gen_ai.usage.output_tokens': '$ai_output_tokens',
    'gen_ai.request.model': '$ai_model',
    'gen_ai.provider.name': '$ai_provider',
}

const JSON_PARSE_PROPERTIES = new Set(['$ai_input', '$ai_output_choices'])

function getEventType(operationName?: unknown): string {
    switch (operationName) {
        case 'chat':
            return '$ai_generation'
        case 'embeddings':
            return '$ai_embedding'
        default:
            return '$ai_span'
    }
}

function transformSpanToAiEvent(
    span: OtelSpan,
    resourceAttrs: Record<string, unknown>,
    distinctId: string
): { event: string; distinct_id: string; properties: Record<string, unknown>; timestamp?: string } {
    const attrs = span.attributes ?? {}

    const properties: Record<string, unknown> = {
        $ai_trace_id: span.traceId,
        $ai_span_id: span.spanId,
        $ai_parent_id: span.parentSpanId ?? undefined,
        $ai_ingestion_source: 'otel',
    }

    for (const [otelKey, phKey] of Object.entries(ATTRIBUTE_MAP)) {
        if (attrs[otelKey] !== undefined) {
            let value = attrs[otelKey]
            if (JSON_PARSE_PROPERTIES.has(phKey) && typeof value === 'string') {
                try {
                    value = JSON.parse(value)
                } catch {
                    // Keep original string value if parsing fails
                }
            }
            properties[phKey] = value
        }
    }

    for (const [key, value] of Object.entries(attrs)) {
        if (!(key in ATTRIBUTE_MAP) && !(key in properties)) {
            properties[key] = value
        }
    }

    for (const [key, value] of Object.entries(resourceAttrs)) {
        if (!(key in properties)) {
            properties[key] = value
        }
    }

    let timestamp: string | undefined
    if (span.startTimeUnixNano) {
        const nanos = typeof span.startTimeUnixNano === 'string' ? BigInt(span.startTimeUnixNano) : span.startTimeUnixNano
        const millis = Number(BigInt(nanos) / BigInt(1_000_000))
        timestamp = new Date(millis).toISOString()
    }

    return {
        event: getEventType(attrs['gen_ai.operation.name']),
        distinct_id: distinctId,
        properties,
        timestamp,
    }
}

export function createExpandOtelRawDataStep<T extends PostTeamPreprocessingSubpipelineInput>(
    kafkaProducer: KafkaProducerWrapper
): ProcessingStep<T, T> {
    return async function expandOtelRawDataStep(input: T): Promise<PipelineResult<T>> {
        const event = input.eventWithTeam.event

        if (event.event !== '$ai_raw_data' || event.properties?.format !== 'otel_trace') {
            return ok(input)
        }

        const otelData = event.properties?.data as OtelTraceData | undefined
        if (!otelData?.resourceSpans) {
            return drop('invalid_otel_data')
        }

        const sideEffects: Promise<unknown>[] = []
        const distinctId = event.distinct_id
        const token = input.eventWithTeam.event.token ?? input.headers.token

        if (!token) {
            return drop('missing_token')
        }

        for (const rs of otelData.resourceSpans) {
            const resourceAttrs = rs.resource?.attributes ?? {}

            for (const ss of rs.scopeSpans ?? []) {
                for (const span of ss.spans ?? []) {
                    const aiEvent = transformSpanToAiEvent(span, resourceAttrs, distinctId)
                    const uuid = randomUUID()

                    sideEffects.push(
                        kafkaProducer.produce({
                            topic: KAFKA_EVENTS_PLUGIN_INGESTION,
                            key: `${token}:${distinctId}` as MessageKey,
                            value: Buffer.from(
                                JSON.stringify({
                                    token,
                                    distinct_id: distinctId,
                                    uuid,
                                    data: JSON.stringify(aiEvent),
                                })
                            ),
                        })
                    )
                }
            }
        }

        return drop('otel_expanded', sideEffects)
    }
}
