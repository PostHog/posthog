import type { Meta, StoryObj } from '@storybook/react'
import { fireEvent, within } from '@testing-library/dom'


import { mswDecorator } from '~/mocks/browser'

import { ClustersView } from './ClustersView'
import type { Cluster } from './types'

const clusters: Cluster[] = ['Delivery questions', 'Plant care'].map((title, clusterId) => ({
    cluster_id: clusterId,
    title,
    description: clusterId
        ? 'Choosing a watering schedule and checking leaf health.'
        : 'Checking an order and reporting a damaged parcel.',
    size: 8,
    centroid: [],
    centroid_x: clusterId * 4,
    centroid_y: 0,
    traces: Object.fromEntries(
        Array.from({ length: 8 }, (_, rank) => {
            const id = `trace-${clusterId}-${rank}`
            return [
                id,
                {
                    trace_id: id,
                    rank,
                    distance_to_centroid: 1,
                    x: clusterId * 4 + Math.cos(rank),
                    y: Math.sin(rank),
                    timestamp: '2026-08-01T10:00:00Z',
                },
            ]
        })
    ),
}))
const runId = '2_trace_20260801_120000'
const config = {
    enabled: true,
    event_filters: [],
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
}

const meta: Meta<typeof ClustersView> = {
    title: 'Scenes-App/AI observability/ClustersView',
    component: ClustersView,
    parameters: {
        layout: 'padded',
        mockDate: '2026-08-01T12:00:00Z',
        testOptions: { snapshotBrowsers: [], waitForSelector: '[data-attr="clusters-card-title-link"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/llm_analytics/clustering_config/': config,
                '/api/environments/:team_id/llm_analytics/clustering_jobs/': { results: [] },
            },
            post: {
                '/api/environments/:team_id/query/:query_kind/': async ({ request }) => {
                    const { query } = (await request.json()) as { query: { query?: string } }
                    const sql = String(query.query ?? '')
                    if (sql.includes('as total_items')) {
                        return {
                            results: [
                                [
                                    runId,
                                    '2026-07-25T00:00:00Z',
                                    '2026-08-01T12:00:00Z',
                                    16,
                                    JSON.stringify(clusters),
                                    '2026-08-01T12:00:00Z',
                                    '{}',
                                    'trace',
                                ],
                            ],
                        }
                    }
                    if (sql.includes('as run_id')) {
                        return { results: [[runId, '2026-08-01T12:00:00Z', '2026-08-01T12:00:00Z']] }
                    }
                    if (sql.includes('as item_id')) {
                        return {
                            results: clusters.flatMap((cluster) =>
                                Object.keys(cluster.traces).map((id, index) => [
                                    id,
                                    0.002 * (index + 1),
                                    index + 0.5,
                                    400,
                                    80,
                                    index === 7 ? 1 : 0,
                                ])
                            ),
                        }
                    }
                    return { results: [] }
                },
            },
        }),
    ],
    render: () => (
        <div className="w-[1200px] max-w-full">
            <ClustersView />
        </div>
    ),
}
export default meta
type Story = StoryObj<typeof ClustersView>

export const Overview: Story = {}

export const Narrow: Story = {
    render: () => (
        <div className="w-[800px] max-w-full">
            <ClustersView />
        </div>
    ),
}

export const ExpandedCluster: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText('Delivery questions')
        fireEvent.click(canvas.getAllByRole('button', { name: 'Show more' })[0])
        await canvas.findByText('View cluster details')
    },
}

export const Disabled: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/environments/:team_id/llm_analytics/clustering_config/': { ...config, enabled: false } },
        }),
    ],
}
