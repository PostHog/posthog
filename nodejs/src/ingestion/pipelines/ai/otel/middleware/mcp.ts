import { OTEL_MCP_EVENT_NAME_PREFIX } from '~/ingestion/common/ai-event-types'
import { STRIP_ATTRIBUTES, normalizeGroups, otelSpanDurationNanos } from '~/ingestion/pipelines/ai/otel/span-properties'
import { PluginEvent } from '~/plugin-scaffold'

import { OtelLibraryMiddleware } from './types'

const RENAMED_ATTRIBUTES = Object.entries({
    'mcp.protocol.version': '$mcp_protocol_version',
    'mcp.session.id': '$session_id',
    'gen_ai.tool.name': '$mcp_tool_name',
    'service.name': '$mcp_server_name',
    'service.version': '$mcp_server_version',
})

// The SDKs put the tool, prompt or resource a request addressed in `$mcp_resource_name`.
const RESOURCE_NAME_ATTRIBUTES = ['gen_ai.tool.name', 'gen_ai.prompt.name', 'mcp.resource.uri']

const DROPPED_ATTRIBUTES = new Set([
    ...STRIP_ATTRIBUTES,
    ...RENAMED_ATTRIBUTES.map(([otelKey]) => otelKey),
    ...RESOURCE_NAME_ATTRIBUTES,
    'error.type',
    'mcp.method.name',
    '$otel_span_name',
    '$otel_start_time_unix_nano',
    '$otel_end_time_unix_nano',
    '$otel_status_code',
    '$otel_status_message',
])

function attribute(props: Record<string, unknown>, key: string): unknown {
    const value = props[key]
    return value === '' || value === null ? undefined : value
}

function process(event: PluginEvent): void {
    const props = event.properties
    if (!props) {
        return
    }

    const resourceName = RESOURCE_NAME_ATTRIBUTES.map((key) => attribute(props, key)).find((v) => v !== undefined)
    if (resourceName !== undefined) {
        props['$mcp_resource_name'] = resourceName
    }

    // A JSON-RPC error response sets the status code, even where the SDK leaves the span status unset.
    const errorType = attribute(props, 'error.type') ?? attribute(props, 'rpc.response.status_code')
    props['$mcp_is_error'] = props['$otel_status_code'] === 'error' || errorType !== undefined
    if (errorType !== undefined) {
        props['$mcp_error_type'] = String(errorType)
    }
    const errorMessage = attribute(props, '$otel_status_message')
    if (errorMessage !== undefined) {
        props['$mcp_error_message'] = errorMessage
    }

    const duration = otelSpanDurationNanos(props)
    if (duration !== undefined) {
        props['$mcp_duration_ms'] = Number(duration) / 1_000_000
    }

    for (const [otelKey, mcpKey] of RENAMED_ATTRIBUTES) {
        const value = attribute(props, otelKey)
        if (value !== undefined) {
            props[mcpKey] = value
        }
    }
    for (const key of DROPPED_ATTRIBUTES) {
        delete props[key]
    }
    normalizeGroups(event)

    props['$mcp_source'] = 'posthog_mcp_analytics'
}

export const mcp: OtelLibraryMiddleware = {
    name: 'mcp',
    matches: (event) => event.event.startsWith(OTEL_MCP_EVENT_NAME_PREFIX),
    process,
}
