import { PluginEvent } from '@posthog/plugin-scaffold'

import { parseJSON } from '../../../utils/json-parse'

const ATTRIBUTE_MAP: Record<string, string> = {
    'gen_ai.input.messages': '$ai_input',
    'gen_ai.output.messages': '$ai_output_choices',
    'gen_ai.usage.input_tokens': '$ai_input_tokens',
    'gen_ai.usage.output_tokens': '$ai_output_tokens',
    'gen_ai.request.model': '$ai_model',
    'gen_ai.provider.name': '$ai_provider',
    'server.address': '$ai_base_url',
    'telemetry.sdk.name': '$ai_lib',
    'telemetry.sdk.version': '$ai_lib_version',
    $otel_span_name: '$ai_span_name',
}

const FALLBACK_ATTRIBUTE_MAP: Record<string, string> = {
    'gen_ai.system': '$ai_provider',
    'gen_ai.response.model': '$ai_model',
}

const STRIP_ATTRIBUTES = new Set(['telemetry.sdk.language', 'gen_ai.operation.name', 'posthog.ai.debug'])

const JSON_PARSE_PROPERTIES = new Set(['$ai_input', '$ai_output_choices'])

export function mapOtelAttributes(event: PluginEvent): void {
    if (!event.properties) {
        return
    }

    for (const [otelKey, phKey] of Object.entries(ATTRIBUTE_MAP)) {
        if (event.properties[otelKey] !== undefined) {
            let value = event.properties[otelKey]
            if (JSON_PARSE_PROPERTIES.has(phKey) && typeof value === 'string') {
                try {
                    value = parseJSON(value)
                } catch {
                    // Keep original string value if parsing fails
                }
            }
            event.properties[phKey] = value
            delete event.properties[otelKey]
        }
    }

    for (const [otelKey, phKey] of Object.entries(FALLBACK_ATTRIBUTE_MAP)) {
        if (event.properties[otelKey] !== undefined && event.properties[phKey] === undefined) {
            event.properties[phKey] = event.properties[otelKey]
        }
        delete event.properties[otelKey]
    }

    computeLatency(event)
    promoteRootSpanToTrace(event)

    for (const key of STRIP_ATTRIBUTES) {
        delete event.properties[key]
    }
}

function computeLatency(event: PluginEvent): void {
    const props = event.properties!
    const startStr = props['$otel_start_time_unix_nano']
    const endStr = props['$otel_end_time_unix_nano']

    if (typeof startStr === 'string' && typeof endStr === 'string') {
        const start = BigInt(startStr)
        const end = BigInt(endStr)
        if (end > start) {
            props['$ai_latency'] = Number(end - start) / 1_000_000_000
        }
    }

    delete props['$otel_start_time_unix_nano']
    delete props['$otel_end_time_unix_nano']
}

function promoteRootSpanToTrace(event: PluginEvent): void {
    if (event.event === '$ai_span' && !event.properties!['$ai_parent_id']) {
        event.event = '$ai_trace'
    }
}
