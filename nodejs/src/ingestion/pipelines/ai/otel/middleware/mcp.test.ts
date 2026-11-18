import { convertOtelEvent } from '~/ingestion/pipelines/ai/otel/index'
import { createEvent } from '~/ingestion/pipelines/ai/otel/test-helpers'

// Spans as capture hands them over, recorded from the MCP Python SDK 2.3.0 OpenTelemetryMiddleware
// serving over Streamable HTTP.
const RESOURCE = {
    'service.name': 'weather-mcp',
    'service.version': '1.4.0',
    'service.instance.id': 'cbcd2400-253e-4b14-93d5-6a3d468f66e1',
}

const spanProps = (overrides: Record<string, unknown>): Record<string, unknown> => ({
    ...RESOURCE,
    'mcp.protocol.version': '2026-07-28',
    $ai_trace_id: 'ae42a25654df1ec33dc15ef31a0a4709',
    $ai_span_id: 'f9e8044920192778',
    $ai_parent_id: '136abaaddd9ff127',
    $ai_ingestion_source: 'otel',
    $otel_start_time_unix_nano: '1794965334668386000',
    $otel_end_time_unix_nano: '1794965334668965000',
    ...overrides,
})

const convert = (event: string, properties: Record<string, unknown>): Record<string, unknown> => {
    const pluginEvent = createEvent(event, properties)
    convertOtelEvent(pluginEvent)
    return pluginEvent.properties!
}

const SHARED_OUTPUT = {
    'service.instance.id': RESOURCE['service.instance.id'],
    $mcp_source: 'posthog_mcp_analytics',
    $mcp_protocol_version: '2026-07-28',
    $mcp_server_name: 'weather-mcp',
    $mcp_server_version: '1.4.0',
    $mcp_duration_ms: 0.579,
    $ai_trace_id: 'ae42a25654df1ec33dc15ef31a0a4709',
    $ai_span_id: 'f9e8044920192778',
    $ai_parent_id: '136abaaddd9ff127',
    $ai_ingestion_source: 'otel',
}

describe('mcp middleware', () => {
    it.each([
        [
            'a successful tool call',
            '$mcp_tool_call',
            {
                'mcp.method.name': 'tools/call',
                'jsonrpc.request.id': '3',
                'gen_ai.operation.name': 'execute_tool',
                'gen_ai.tool.name': 'get_forecast',
                $otel_span_name: 'tools/call get_forecast',
            },
            {
                'jsonrpc.request.id': '3',
                $mcp_tool_name: 'get_forecast',
                $mcp_resource_name: 'get_forecast',
                $mcp_is_error: false,
            },
        ],
        [
            'a tool call that returned isError',
            '$mcp_tool_call',
            {
                'mcp.method.name': 'tools/call',
                'jsonrpc.request.id': '4',
                'gen_ai.operation.name': 'execute_tool',
                'gen_ai.tool.name': 'get_alerts',
                'error.type': 'tool_error',
                $otel_span_name: 'tools/call get_alerts',
                $otel_status_code: 'error',
            },
            {
                'jsonrpc.request.id': '4',
                $mcp_tool_name: 'get_alerts',
                $mcp_resource_name: 'get_alerts',
                $mcp_is_error: true,
                $mcp_error_type: 'tool_error',
            },
        ],
        [
            'a call that failed with a JSON-RPC error',
            '$mcp_tool_call',
            {
                'mcp.method.name': 'tools/call',
                'gen_ai.tool.name': 'get_alerts',
                'error.type': '-32602',
                'rpc.response.status_code': '-32602',
                $otel_status_code: 'error',
                $otel_status_message: 'Invalid request parameters',
            },
            {
                'rpc.response.status_code': '-32602',
                $mcp_tool_name: 'get_alerts',
                $mcp_resource_name: 'get_alerts',
                $mcp_is_error: true,
                $mcp_error_type: '-32602',
                $mcp_error_message: 'Invalid request parameters',
            },
        ],
        [
            'a call to an unknown tool, as the TypeScript SDK records it',
            '$mcp_tool_call',
            {
                'mcp.method.name': 'tools/call',
                'gen_ai.tool.name': 'does-not-exist',
                'rpc.response.status_code': '-32602',
            },
            {
                'rpc.response.status_code': '-32602',
                $mcp_tool_name: 'does-not-exist',
                $mcp_resource_name: 'does-not-exist',
                $mcp_is_error: true,
                $mcp_error_type: '-32602',
            },
        ],
        [
            'a prompt get',
            '$mcp_prompt_get',
            { 'mcp.method.name': 'prompts/get', 'gen_ai.prompt.name': 'plan_trip' },
            { $mcp_resource_name: 'plan_trip', $mcp_is_error: false },
        ],
        [
            'a resource read',
            '$mcp_resource_read',
            { 'mcp.method.name': 'resources/read', 'mcp.resource.uri': 'weather://cities' },
            { $mcp_resource_name: 'weather://cities', $mcp_is_error: false },
        ],
        [
            'a span on a stateful session',
            '$mcp_tools_list',
            { 'mcp.method.name': 'tools/list', 'mcp.session.id': 'b1946ac9-2492-4d1e-9b5f-2e4d7a6a0c11' },
            { $session_id: 'b1946ac9-2492-4d1e-9b5f-2e4d7a6a0c11', $mcp_is_error: false },
        ],
        [
            'blank and numeric attributes',
            '$mcp_tool_call',
            {
                'mcp.method.name': 'tools/call',
                'mcp.session.id': '',
                'gen_ai.tool.name': '',
                'error.type': '',
                'rpc.response.status_code': -32602,
            },
            { 'rpc.response.status_code': -32602, $mcp_is_error: true, $mcp_error_type: '-32602' },
        ],
        [
            'groups and identity attributes',
            '$mcp_tools_list',
            {
                'mcp.method.name': 'tools/list',
                $groups: '{"company":"acme"}',
                'user.id': 'user-1',
                'posthog.distinct_id': 'user-1',
            },
            { $groups: { company: 'acme' }, $mcp_is_error: false },
        ],
    ])('maps %s onto the SDK vocabulary', (_label, event, attributes, expected) => {
        expect(convert(event, spanProps(attributes))).toEqual({
            ...SHARED_OUTPUT,
            ...expected,
        })
    })

    it('leaves gen_ai spans to the AI middlewares', () => {
        const props = convert('$ai_span', spanProps({ 'gen_ai.tool.name': 'get_forecast' }))
        expect(props['$mcp_tool_name']).toBeUndefined()
        expect(props['$ai_latency']).toBeCloseTo(0.000579)
    })
})
