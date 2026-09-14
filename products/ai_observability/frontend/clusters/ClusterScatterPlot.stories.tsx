import type { Meta, StoryObj } from '@storybook/react'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { useStorybookMocks } from '~/mocks/browser'

import { ClusterScatterPlot } from './ClusterScatterPlot'
import { clustersLogic } from './clustersLogic'
import { NOISE_CLUSTER_ID } from './constants'
import { Cluster, ClusterItemInfo, ClusteringRun } from './types'

// Deterministic ring of points around a centroid — random coordinates would churn the snapshot.
function makeTraces(clusterId: number, cx: number, cy: number, count: number): Record<string, ClusterItemInfo> {
    const traces: Record<string, ClusterItemInfo> = {}
    for (let i = 0; i < count; i++) {
        const angle = (i / count) * Math.PI * 2
        const radius = 0.4 + (i % 5) * 0.12
        const id = `c${clusterId}-t${i}`
        traces[id] = {
            distance_to_centroid: radius,
            rank: i,
            x: cx + Math.cos(angle) * radius,
            y: cy + Math.sin(angle) * radius,
            timestamp: '2026-08-01T10:00:00Z',
            trace_id: id,
        }
    }
    return traces
}

function makeCluster(clusterId: number, title: string, cx: number, cy: number, count: number): Cluster {
    return {
        cluster_id: clusterId,
        size: count,
        title,
        description: '',
        traces: makeTraces(clusterId, cx, cy, count),
        centroid: [],
        centroid_x: cx,
        centroid_y: cy,
    }
}

const run: ClusteringRun = {
    runId: '2_trace_20260801_120000',
    windowStart: '2026-07-25T00:00:00Z',
    windowEnd: '2026-08-01T00:00:00Z',
    totalItemsAnalyzed: 120,
    timestamp: '2026-08-01T12:00:00Z',
    level: 'trace',
    clusters: [
        makeCluster(0, 'Refund requests', -2, 1.5, 28),
        makeCluster(1, 'Password resets', 2, 2, 24),
        makeCluster(2, 'Billing questions', 1.5, -2, 22),
        makeCluster(NOISE_CLUSTER_ID, 'Outliers', -3, -2.5, 10),
    ],
}

const meta: Meta<typeof ClusterScatterPlot> = {
    title: 'Scenes-App/AI observability/ClusterScatterPlot',
    component: ClusterScatterPlot,
    // Excluded from visual-regression snapshots: it mounts clustersLogic (and its on-mount query
    // loaders), which doesn't settle within the runner's screenshot timeout under CI load. It still
    // renders the real chart in interactive Storybook for inspection.
    tags: ['test-skip'],
    parameters: {
        layout: 'padded',
    },
    render: () => {
        // The runs list loader fires on mount; keep it empty so the seeded run below is what renders.
        useStorybookMocks({
            post: {
                '/api/environments/:team_id/query/': () => [200, { results: [] }],
            },
        })
        useOnMountEffect(() => {
            clustersLogic.mount()
            clustersLogic.actions.loadClusteringRunSuccess(run)
        })
        return (
            <div className="max-w-3xl">
                <ClusterScatterPlot />
            </div>
        )
    },
}
export default meta

type Story = StoryObj<typeof ClusterScatterPlot>

export const Overview: Story = {}
