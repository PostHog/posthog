import { Decorator, Meta, StoryObj } from '@storybook/react'
import { useEffect, useRef } from 'react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

// The SQL editor scene gates on warehouse-objects access; grant it on the storybook app context
// before the story mounts and restore the original on unmount so story order can't leak.
const grantWarehouseAccess: Decorator = function GrantWarehouseAccess(Story): JSX.Element {
    const appContext = (window as any).POSTHOG_APP_CONTEXT
    const original = useRef<{ value: unknown }>()
    if (appContext && !original.current) {
        original.current = { value: appContext.resource_access_control }
        appContext.resource_access_control = {
            ...appContext.resource_access_control,
            [AccessControlResourceType.WarehouseObjects]: AccessControlLevel.Editor,
        }
    }
    useEffect(
        () => () => {
            if (appContext && original.current) {
                appContext.resource_access_control = original.current.value
            }
        },
        [appContext]
    )
    return <Story />
}

// Top tools per server — mirrors the first recipe in the MCP analytics docs (queries.mdx).
const SAMPLE_SQL = `SELECT
    properties.$mcp_server_name AS server,
    properties.$mcp_tool_name AS tool,
    count() AS calls,
    round(avg(toFloat(properties.$mcp_duration_ms))) AS avg_duration_ms,
    countIf(toBool(properties.$mcp_is_error)) AS errors
FROM events
WHERE event = 'mcp_tool_call' AND timestamp > now() - INTERVAL 7 DAY
GROUP BY server, tool
ORDER BY calls DESC
LIMIT 20`

// Mock results for the "top tools per server" query. The visual-regression snapshot captures the
// editor with the query pre-loaded but NOT run (driving Run in the snapshot races the async query
// against Storybook's story-prepare step and flakes). These results back the query when a human
// presses Run locally — that's how the doc screenshot with a populated grid was captured.
const SQL_RESULTS = {
    columns: ['server', 'tool', 'calls', 'avg_duration_ms', 'errors'],
    types: ['String', 'String', 'UInt64', 'Float64', 'UInt64'],
    hasMore: false,
    results: [
        ['posthog', 'execute-sql', 1480, 3525, 144],
        ['posthog', 'read-data-schema', 760, 1298, 3],
        ['posthog', 'query-trends', 540, 2122, 5],
        ['posthog', 'insight-create', 410, 727, 8],
        ['posthog', 'dashboard-create', 260, 940, 2],
        ['posthog', 'feature-flag-list', 180, 510, 1],
        ['posthog', 'cohort-create', 95, 1620, 6],
        ['filesystem', 'exec', 5200, 2290, 208],
        ['filesystem', 'read-file', 980, 180, 3],
        ['filesystem', 'write-file', 420, 240, 11],
    ],
}

// The empty-warehouse notice in the sidebar renders a SourceIcon per provider, each of which shows a
// LemonSkeleton until availableSourcesLogic resolves. Without this mock the skeletons never settle and
// the visual-regression runner times out waiting for loaders to disappear.
const AVAILABLE_SOURCES = {
    Postgres: { name: 'Postgres', iconPath: '/static/services/postgres.png', fields: [], caption: '', featured: true },
    Stripe: { name: 'Stripe', iconPath: '/static/services/stripe.png', fields: [], caption: '', featured: true },
    GoogleAds: {
        name: 'GoogleAds',
        iconPath: '/static/services/google-ads.png',
        fields: [],
        caption: '',
        featured: true,
    },
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data Warehouse/SQL Editor',
    decorators: [
        grantWarehouseAccess,
        mswDecorator({
            get: {
                '/api/environments/:team_id/external_data_sources/wizard': () => [200, AVAILABLE_SOURCES],
            },
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    const kind = body?.query?.kind
                    if (kind === 'DatabaseSchemaQuery') {
                        return [200, { tables: {} }]
                    }
                    if (kind === 'HogQLMetadata') {
                        return [200, { errors: [], warnings: [], notices: [], isValid: true }]
                    }
                    return [200, SQL_RESULTS]
                },
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-07',
        // open_query pre-fills the editor with SAMPLE_SQL but does not auto-run it, so the snapshot
        // captures the loaded query with an empty results pane. (SQL_RESULTS backs the query when Run
        // is pressed locally — see its comment.)
        pageUrl: urls.sqlEditor({ query: SAMPLE_SQL }),
        testOptions: {
            waitForSelector: '.monaco-editor',
            viewport: { width: 1600, height: 900 },
        },
    },
}
export default meta

type Story = StoryObj<{}>
export const TopToolsPerServer: Story = {}
