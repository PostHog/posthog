import api, { ApiRequest } from 'lib/api'

import type { SearchableEntity } from '~/types'

import type { WebMcpTool, WebMcpToolResult } from './webMcpTypes'

function textResult(data: unknown): WebMcpToolResult {
    return {
        content: [{ type: 'text', text: typeof data === 'string' ? data : JSON.stringify(data, null, 2) }],
    }
}

function errorResult(message: string): WebMcpToolResult {
    return {
        content: [{ type: 'text', text: message }],
        isError: true,
    }
}

async function safeExecute(fn: () => Promise<unknown>): Promise<WebMcpToolResult> {
    try {
        return textResult(await fn())
    } catch (e: any) {
        return errorResult(e.message || 'An unexpected error occurred')
    }
}

/**
 * Builds the curated set of PostHog tools for WebMCP registration.
 *
 * Tool metadata (names, descriptions) mirrors the MCP server's tool-definitions.json
 * but execution goes directly through the PostHog REST API (cookie-authenticated),
 * avoiding the need for a backend proxy or MCP protocol client.
 */
export function buildWebMcpTools(): WebMcpTool[] {
    return [
        {
            name: 'posthog:dashboards-get-all',
            description:
                'Get all dashboards in the PostHog project with optional filtering. Can filter by search term.',
            inputSchema: {
                type: 'object',
                properties: {
                    search: { type: 'string', description: 'Search term to filter dashboards by name' },
                },
            },
            annotations: { readOnly: true },
            execute: (args) =>
                safeExecute(() => {
                    const params: Record<string, string> = {}
                    if (args.search) {
                        params.search = String(args.search)
                    }
                    return api.dashboards.list(params)
                }),
        },
        {
            name: 'posthog:dashboard-get',
            description: 'Get a specific PostHog dashboard by ID, including insights/tiles that are on the dashboard.',
            inputSchema: {
                type: 'object',
                properties: {
                    id: { type: 'number', description: 'Dashboard ID' },
                },
                required: ['id'],
            },
            annotations: { readOnly: true },
            execute: (args) => safeExecute(() => api.dashboards.get(Number(args.id))),
        },
        {
            name: 'posthog:feature-flags-get-all',
            description: 'Get all feature flags in the PostHog project.',
            inputSchema: {
                type: 'object',
                properties: {
                    limit: { type: 'number', description: 'Maximum number of results' },
                    offset: { type: 'number', description: 'Pagination offset' },
                },
            },
            annotations: { readOnly: true },
            execute: (args) =>
                safeExecute(() => {
                    const params: Record<string, any> = {}
                    if (args.limit) {
                        params.limit = Number(args.limit)
                    }
                    if (args.offset) {
                        params.offset = Number(args.offset)
                    }
                    return new ApiRequest().featureFlags().withQueryString(params).get()
                }),
        },
        {
            name: 'posthog:feature-flag-get',
            description: 'Get a specific PostHog feature flag by ID.',
            inputSchema: {
                type: 'object',
                properties: {
                    id: { type: 'number', description: 'Feature flag ID' },
                },
                required: ['id'],
            },
            annotations: { readOnly: true },
            execute: (args) => safeExecute(() => api.featureFlags.get(Number(args.id))),
        },
        {
            name: 'posthog:insights-get-all',
            description: 'Get all insights in the PostHog project with optional filtering. Can filter by search term.',
            inputSchema: {
                type: 'object',
                properties: {
                    search: { type: 'string', description: 'Search term to filter insights' },
                    saved: { type: 'boolean', description: 'Only show saved insights' },
                },
            },
            annotations: { readOnly: true },
            execute: (args) =>
                safeExecute(() => {
                    const params: Record<string, any> = {}
                    if (args.search) {
                        params.search = String(args.search)
                    }
                    if (args.saved !== undefined) {
                        params.saved = args.saved
                    }
                    return api.insights.list(params)
                }),
        },
        {
            name: 'posthog:insight-get',
            description: 'Get a specific PostHog insight by ID.',
            inputSchema: {
                type: 'object',
                properties: {
                    id: { type: 'number', description: 'Insight ID' },
                },
                required: ['id'],
            },
            annotations: { readOnly: true },
            execute: (args) => safeExecute(() => api.insights.get(Number(args.id))),
        },
        {
            name: 'posthog:surveys-get-all',
            description: 'Get all surveys in the PostHog project with optional filtering.',
            inputSchema: {
                type: 'object',
                properties: {
                    search: { type: 'string', description: 'Search term to filter surveys' },
                },
            },
            annotations: { readOnly: true },
            execute: (args) =>
                safeExecute(() => {
                    const params: Record<string, any> = {}
                    if (args.search) {
                        params.search = String(args.search)
                    }
                    return api.surveys.list(params)
                }),
        },
        {
            name: 'posthog:survey-get',
            description: 'Get a specific PostHog survey by ID.',
            inputSchema: {
                type: 'object',
                properties: {
                    id: { type: 'string', description: 'Survey ID' },
                },
                required: ['id'],
            },
            annotations: { readOnly: true },
            execute: (args) => safeExecute(() => api.surveys.get(String(args.id))),
        },
        {
            name: 'posthog:event-definitions-list',
            description:
                'List all event definitions in the PostHog project with optional filtering. Can filter by search term.',
            inputSchema: {
                type: 'object',
                properties: {
                    search: { type: 'string', description: 'Search term to filter events' },
                    limit: { type: 'number', description: 'Maximum number of results (default 50)' },
                },
            },
            annotations: { readOnly: true },
            execute: (args) =>
                safeExecute(() => {
                    const params: Record<string, any> = {}
                    if (args.search) {
                        params.search = String(args.search)
                    }
                    if (args.limit) {
                        params.limit = Number(args.limit)
                    }
                    return api.eventDefinitions.list(params)
                }),
        },
        {
            name: 'posthog:entity-search',
            description:
                'Search for PostHog entities by name or description across insights, dashboards, experiments, feature flags, and more.',
            inputSchema: {
                type: 'object',
                properties: {
                    q: { type: 'string', description: 'Search query string' },
                    entities: {
                        type: 'array',
                        items: { type: 'string' },
                        description:
                            'Entity types to search (e.g. insight, dashboard, experiment, feature_flag, survey)',
                    },
                },
                required: ['q'],
            },
            annotations: { readOnly: true },
            execute: (args) =>
                safeExecute(() =>
                    api.search.list({
                        q: String(args.q),
                        entities: args.entities as SearchableEntity[] | undefined,
                    })
                ),
        },
    ]
}
