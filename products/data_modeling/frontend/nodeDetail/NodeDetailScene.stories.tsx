import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { useEffect, useRef } from 'react'

import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { NodeDetailScene } from './NodeDetailScene'

const grantWarehouseAccess: Decorator = function GrantWarehouseAccess(Story): JSX.Element {
    const appContext = window.POSTHOG_APP_CONTEXT
    const original = useRef(appContext ? { appContext, access: appContext.resource_access_control } : null)
    if (appContext) {
        appContext.resource_access_control = {
            ...appContext.resource_access_control,
            [AccessControlResourceType.WarehouseObjects]: AccessControlLevel.Editor,
        }
    }
    useEffect(
        () => () => {
            if (original.current) {
                original.current.appContext.resource_access_control = original.current.access
            }
        },
        [appContext]
    )
    return <Story />
}

const node = {
    id: 'example-node',
    name: 'monthly_revenue_summary_by_region_and_channel',
    type: 'view',
    dag: 'example-dag',
    saved_query_id: 'example-view',
    created_at: '2026-01-10T10:00:00Z',
    updated_at: '2026-01-10T10:00:00Z',
    upstream_count: 2,
    downstream_count: 3,
}
const savedQuery = {
    id: node.saved_query_id,
    name: node.name,
    is_materialized: false,
    created_at: node.created_at,
    created_by: { id: 1, uuid: 'example-user', first_name: 'Casey', last_name: 'Morgan', email: 'casey@example.com' },
    user_access_level: 'editor',
    query: {
        kind: 'HogQLQuery',
        query: 'SELECT region, channel, sum(amount) AS revenue\nFROM orders\nGROUP BY region, channel',
    },
    columns: [
        { name: 'region', type: 'string' },
        { name: 'channel', type: 'string' },
        { name: 'revenue', type: 'float' },
    ],
}

const meta: Meta<typeof NodeDetailScene> = {
    title: 'Products/Data modeling/Node detail scene',
    component: NodeDetailScene,
    args: { id: node.id },
    decorators: [
        grantWarehouseAccess,
        (Story) => (
            <div className="@container/main-content">
                <Story />
            </div>
        ),
        mswDecorator({}),
    ],
    parameters: {
        layout: 'fullscreen',
        msw: {
            mocks: {
                get: {
                    '/api/environments/:team_id/data_modeling_nodes/:id/': () => [200, node],
                    '/api/environments/:team_id/warehouse_saved_queries/:id/': () => [200, savedQuery],
                },
            },
        },
        pageUrl: urls.nodeDetail(node.id, 'query'),
        mockDate: '2026-09-14',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof NodeDetailScene>
export const View: Story = {}
export const NarrowView: Story = {
    decorators: [
        (Story) => (
            <div className="@container/main-content w-128 max-w-full">
                <Story />
            </div>
        ),
    ],
}

export const PaginatedColumns: Story = {
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/environments/:team_id/data_modeling_nodes/:id/': () => [200, node],
                    '/api/environments/:team_id/warehouse_saved_queries/:id/': () => [
                        200,
                        {
                            ...savedQuery,
                            columns: Array.from({ length: 11 }, (_, index) => ({
                                name: `column_${index + 1}`,
                                hogql_value: `column_${index + 1}`,
                                type: 'string',
                                schema_valid: true,
                            })),
                        },
                    ],
                },
            },
        },
    },
}

export const MaterializedView: Story = {
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/environments/:team_id/data_modeling_nodes/:id/': () => [200, { ...node, type: 'matview' }],
                    '/api/environments/:team_id/warehouse_saved_queries/:id/': () => [
                        200,
                        {
                            ...savedQuery,
                            is_materialized: true,
                            status: 'Completed',
                            sync_frequency: '1hour',
                        },
                    ],
                    '/api/projects/:team_id/data_modeling_jobs/': () => [200, { results: [], count: 0, next: null }],
                },
            },
        },
    },
}

export const NarrowMaterializedView: Story = {
    ...MaterializedView,
    decorators: NarrowView.decorators,
}

const suspension = {
    clickhouse: { at: '2026-09-13T12:00:00Z', reason: 'The source table orders is unavailable.', job_id: 'run-0' },
}

export const SuspendedWithRunHistory: Story = {
    parameters: {
        pageUrl: urls.nodeDetail(node.id, 'materialization'),
        msw: {
            mocks: {
                get: {
                    '/api/environments/:team_id/data_modeling_nodes/:id/': () => [
                        200,
                        { ...node, type: 'matview', suspended: suspension, last_run_status: 'Failed' },
                    ],
                    '/api/environments/:team_id/warehouse_saved_queries/:id/': () => [
                        200,
                        {
                            ...savedQuery,
                            is_materialized: true,
                            status: 'Failed',
                            sync_frequency: '1hour',
                            suspended: suspension,
                        },
                    ],
                    '/api/projects/:team_id/data_modeling_jobs/': ({ request }: { request: Request }) => {
                        const params = new URL(request.url).searchParams
                        // Every run this model has failed, so the last-successful-sync lookup finds nothing.
                        if (params.get('status') === 'Completed') {
                            return [200, { count: 0, next: null, results: [] }]
                        }
                        const offset = Number(params.get('offset') ?? 0)
                        return [
                            200,
                            {
                                count: 25,
                                next: offset < 20 ? '/next' : null,
                                results: Array.from({ length: Math.min(10, 25 - offset) }, (_, index) => ({
                                    id: `run-${offset + index}`,
                                    status: 'Failed',
                                    rows_materialized: 0,
                                    rows_expected: null,
                                    error: 'The source table orders is unavailable.',
                                    created_at: '2026-09-13T12:00:00Z',
                                    last_run_at: '2026-09-13T12:00:00Z',
                                    updated_at: '2026-09-13T12:00:03Z',
                                })),
                            },
                        ]
                    },
                },
            },
        },
    },
}

export const NarrowSuspendedWithRunHistory: Story = {
    ...SuspendedWithRunHistory,
    decorators: NarrowView.decorators,
}
