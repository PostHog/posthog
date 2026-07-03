import { Meta, StoryObj } from '@storybook/react'
import { combineUrl } from 'kea-router'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { NodeKind } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

interface MCPCall {
    uuid: string
    distinctId: string
    timestamp: string
    tool: string
    client: string
    isError: boolean
    durationMs: number
    intent: string
    intentSource: string
    server: string
    conversationId: string
    sessionId: string
    parameters: Record<string, any>
    response: Record<string, any>
    errorMessage?: string
}

const CALLS: MCPCall[] = [
    {
        uuid: '0193f2a1-0000-0000-0000-000000000001',
        distinctId: 'annika@example.com',
        timestamp: '2026-06-07T10:04:42Z',
        tool: 'execute-sql',
        client: 'claude-code/1.2.0',
        isError: true,
        durationMs: 610000,
        intent: 'Retry the tuned dashboard query after the first attempt timed out.',
        intentSource: 'tool_argument',
        server: 'posthog',
        conversationId: 'conv-7f3a',
        sessionId: '0193f2a1-aaaa-bbbb-cccc-000000000001',
        parameters: { query: 'SELECT count() FROM events WHERE ...' },
        response: {},
        errorMessage: 'Estimated query execution time is too long (max_execution_time=600)',
    },
    {
        uuid: '0193f2a1-0000-0000-0000-000000000002',
        distinctId: 'annika@example.com',
        timestamp: '2026-06-07T10:01:10Z',
        tool: 'execute-sql',
        client: 'claude-code/1.2.0',
        isError: false,
        durationMs: 8125,
        intent: 'Run the slow dashboard query with EXPLAIN to find the bottleneck.',
        intentSource: 'tool_argument',
        server: 'posthog',
        conversationId: 'conv-7f3a',
        sessionId: '0193f2a1-aaaa-bbbb-cccc-000000000001',
        parameters: { query: 'EXPLAIN SELECT ...' },
        response: { rows: 1 },
    },
    {
        uuid: '0193f2a1-0000-0000-0000-000000000003',
        distinctId: 'annika@example.com',
        timestamp: '2026-06-07T10:00:05Z',
        tool: 'read-data-schema',
        client: 'claude-code/1.2.0',
        isError: false,
        durationMs: 420,
        intent: 'Look up the events schema before writing SQL.',
        intentSource: 'tool_argument',
        server: 'posthog',
        conversationId: 'conv-7f3a',
        sessionId: '0193f2a1-aaaa-bbbb-cccc-000000000001',
        parameters: { table: 'events' },
        response: { columns: 42 },
    },
    {
        uuid: '0193f2a1-0000-0000-0000-000000000004',
        distinctId: 'sven@example.com',
        timestamp: '2026-06-07T09:31:30Z',
        tool: 'query-trends',
        client: 'cursor-vscode/0.42',
        isError: false,
        durationMs: 2122,
        intent: 'Chart weekly active users for the last quarter.',
        intentSource: 'intent_fallback',
        server: 'posthog',
        conversationId: 'conv-9b21',
        sessionId: '0193f2a1-aaaa-bbbb-cccc-000000000002',
        parameters: { events: ['$pageview'] },
        response: { series: 1 },
    },
    {
        uuid: '0193f2a1-0000-0000-0000-000000000005',
        distinctId: 'sven@example.com',
        timestamp: '2026-06-07T09:30:55Z',
        tool: 'insight-create',
        client: 'cursor-vscode/0.42',
        isError: false,
        durationMs: 727,
        intent: 'Save the weekly active users trend as an insight.',
        intentSource: 'tool_argument',
        server: 'posthog',
        conversationId: 'conv-9b21',
        sessionId: '0193f2a1-aaaa-bbbb-cccc-000000000002',
        parameters: { name: 'WAU' },
        response: { short_id: 'aBcD1234' },
    },
    {
        uuid: '0193f2a1-0000-0000-0000-000000000006',
        distinctId: 'codex-runner',
        timestamp: '2026-06-07T08:17:40Z',
        tool: 'exec',
        client: 'codex-cli',
        isError: false,
        durationMs: 2290,
        intent: 'Run the test suite for the checkout service.',
        intentSource: 'intent_fallback',
        server: 'filesystem',
        conversationId: 'conv-4c08',
        sessionId: '0193f2a1-aaaa-bbbb-cccc-000000000003',
        parameters: { command: 'pnpm test checkout' },
        response: { exit_code: 0 },
    },
    {
        uuid: '0193f2a1-0000-0000-0000-000000000007',
        distinctId: 'codex-runner',
        timestamp: '2026-06-07T08:15:12Z',
        tool: 'feature-flag-list',
        client: 'codex-cli',
        isError: false,
        durationMs: 510,
        intent: 'List active feature flags before editing the rollout.',
        intentSource: 'tool_argument',
        server: 'posthog',
        conversationId: 'conv-4c08',
        sessionId: '0193f2a1-aaaa-bbbb-cccc-000000000003',
        parameters: {},
        response: { count: 18 },
    },
    {
        uuid: '0193f2a1-0000-0000-0000-000000000008',
        distinctId: 'maria@example.com',
        timestamp: '2026-06-07T07:48:03Z',
        tool: 'cohort-create',
        client: 'claude-ai',
        isError: false,
        durationMs: 1620,
        intent: 'Build a cohort of users who hit the new pricing page.',
        intentSource: 'tool_argument',
        server: 'posthog',
        conversationId: 'conv-1d77',
        sessionId: '0193f2a1-aaaa-bbbb-cccc-000000000004',
        parameters: { name: 'Pricing page visitors' },
        response: { id: 91 },
    },
]

const COLUMNS = [
    '*',
    'event',
    'properties.$mcp_tool_name -- Tool',
    'properties.$mcp_client_name -- Client',
    'properties.$mcp_is_error -- Error',
    'properties.$mcp_duration_ms -- Duration (ms)',
    'timestamp',
]

function toRow(call: MCPCall): any[] {
    const properties: Record<string, any> = {
        $mcp_tool_name: call.tool,
        $mcp_intent: call.intent,
        $mcp_intent_source: call.intentSource,
        $mcp_is_error: call.isError,
        $mcp_duration_ms: call.durationMs,
        $mcp_client_name: call.client,
        $mcp_server_name: call.server,
        $mcp_parameters: call.parameters,
        $mcp_response: call.response,
        $mcp_conversation_id: call.conversationId,
        $session_id: call.sessionId,
    }
    if (call.errorMessage) {
        properties.$mcp_error_message = call.errorMessage
    }
    const event = {
        uuid: call.uuid,
        event: 'mcp_tool_call',
        distinct_id: call.distinctId,
        timestamp: call.timestamp,
        properties,
        elements_chain: '',
    }
    // Derive the row tuple from COLUMNS so reordering the columns can't silently desync the mock.
    const valueByColumn: Record<string, any> = {
        '*': event,
        event: 'mcp_tool_call',
        'properties.$mcp_tool_name -- Tool': call.tool,
        'properties.$mcp_client_name -- Client': call.client,
        'properties.$mcp_is_error -- Error': call.isError,
        'properties.$mcp_duration_ms -- Duration (ms)': call.durationMs,
        timestamp: call.timestamp,
    }
    return COLUMNS.map((column) => valueByColumn[column])
}

const mcpEventsResponse = {
    columns: COLUMNS,
    types: [
        'Tuple',
        'String',
        'Nullable(String)',
        'Nullable(String)',
        'Nullable(Boolean)',
        'Nullable(Int64)',
        "DateTime64(6, 'UTC')",
    ],
    hasMore: false,
    results: CALLS.map(toRow),
}

const mcpQuery = {
    kind: NodeKind.DataTableNode,
    full: true,
    source: {
        kind: NodeKind.EventsQuery,
        select: COLUMNS,
        event: 'mcp_tool_call',
        orderBy: ['timestamp DESC'],
        after: '-24h',
    },
    propertiesViaUrl: true,
    showSavedQueries: true,
    showPersistentColumnConfigurator: true,
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Events/MCP Tool Calls',
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind': mcpEventsResponse,
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-07T12:00:00Z',
        pageUrl: combineUrl(urls.activity(ActivityTab.ExploreEvents), {}, { q: mcpQuery }).url,
        testOptions: { waitForSelector: '.DataTable td' },
    },
}
export default meta

type Story = StoryObj<{}>
export const MCPToolCalls: Story = {}
