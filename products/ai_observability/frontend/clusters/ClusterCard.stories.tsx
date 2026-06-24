import type { Meta, StoryObj } from '@storybook/react'

import { ClusterCard } from './ClusterCard'
import { NOISE_CLUSTER_ID } from './constants'
import { Cluster, ClusterMetrics } from './types'

const baseCluster: Cluster = {
    cluster_id: 3,
    size: 128,
    title: 'Refund and cancellation requests',
    description:
        'Users asking the assistant to refund a charge, cancel a subscription, or reverse a recent payment. Often references an order ID or invoice number.',
    traces: {},
    centroid: [],
    centroid_x: 0,
    centroid_y: 0,
}

const baseMetrics: ClusterMetrics = {
    avgCost: 0.0042,
    avgLatency: 2.31,
    avgTokens: 1840,
    totalCost: 0.54,
    errorRate: 0.02,
    errorCount: 3,
    itemCount: 128,
}

const meta: Meta<typeof ClusterCard> = {
    title: 'Scenes-App/AI observability/ClusterCard',
    component: ClusterCard,
    parameters: {
        layout: 'padded',
    },
}
export default meta

type Story = StoryObj<typeof ClusterCard>

const baseArgs = {
    cluster: baseCluster,
    totalTraces: 500,
    isExpanded: false,
    onToggleExpand: () => {},
    traceSummaries: {},
    loadingTraces: false,
    runId: '2_trace_20260101_120000',
    clusteringLevel: 'trace' as const,
    metrics: baseMetrics,
    metricsLoading: false,
}

export const Default: Story = {
    render: (args) => (
        <div className="max-w-2xl">
            <ClusterCard {...args} />
        </div>
    ),
    args: baseArgs,
}

export const OutlierCluster: Story = {
    render: (args) => (
        <div className="max-w-2xl">
            <ClusterCard {...args} />
        </div>
    ),
    args: {
        ...baseArgs,
        cluster: {
            ...baseCluster,
            cluster_id: NOISE_CLUSTER_ID,
            title: 'Outliers',
            description: 'Items that did not fit cleanly into any cluster.',
            size: 17,
        },
    },
}

export const WithoutMetrics: Story = {
    render: (args) => (
        <div className="max-w-2xl">
            <ClusterCard {...args} />
        </div>
    ),
    args: {
        ...baseArgs,
        metrics: undefined,
    },
}

export const Grid: Story = {
    render: (args) => (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {[0, 1, 2, 3, 4, 5].map((id) => (
                <ClusterCard
                    {...args}
                    key={id}
                    cluster={{
                        ...baseCluster,
                        cluster_id: id,
                        title: `Cluster ${id + 1}`,
                    }}
                />
            ))}
            <ClusterCard
                {...args}
                cluster={{
                    ...baseCluster,
                    cluster_id: NOISE_CLUSTER_ID,
                    title: 'Outliers',
                    size: 12,
                }}
            />
        </div>
    ),
    args: baseArgs,
}
