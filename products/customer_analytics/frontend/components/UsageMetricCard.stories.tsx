import type { Meta, StoryObj } from '@storybook/react'

import { UsageMetric } from '~/queries/schema/schema-general'

import { UsageMetricCard, UsageMetricCardSkeleton } from './UsageMetricCard'

const baseNumberMetric: UsageMetric = {
    id: 'synced-rows',
    name: 'Synced rows',
    value: 774000,
    previous: 656000,
    change_from_previous_pct: 0.18,
    format: 'numeric',
    display: 'number',
    interval: 30,
}

const sparklineData = [
    42, 58, 67, 71, 55, 48, 62, 73, 80, 77, 59, 44, 38, 29, 24, 19, 22, 27, 31, 26, 20, 18, 15, 17, 22, 28, 24, 19, 21,
    18,
]

const SPARKLINE_ANCHOR_DATE = new Date('2024-01-30T00:00:00Z')
const sparklineLabels = Array.from({ length: 30 }, (_, i) => {
    const date = new Date(SPARKLINE_ANCHOR_DATE)
    date.setUTCDate(date.getUTCDate() - (29 - i))
    return date.toISOString()
})

const baseSparklineMetric: UsageMetric = {
    id: 'feature-flag-requests',
    name: 'Feature flag requests',
    value: 292_000_000,
    previous: 1_043_000_000,
    change_from_previous_pct: -0.72,
    format: 'numeric',
    display: 'sparkline',
    interval: 30,
    timeseries: sparklineData,
    timeseries_labels: sparklineLabels,
}

const meta: Meta<typeof UsageMetricCard> = {
    title: 'Components/UsageMetricCard',
    component: UsageMetricCard,
    parameters: {
        layout: 'padded',
    },
}
export default meta

type Story = StoryObj<typeof UsageMetricCard>

const Grid = ({ metrics }: { metrics: UsageMetric[] }): JSX.Element => (
    <div style={{ width: 1280 }}>
        <div className="@container">
            <div className="grid grid-cols-1 @md:grid-cols-2 @xl:grid-cols-4 gap-4 p-4">
                {metrics.map((metric) => (
                    <UsageMetricCard key={metric.id} metric={metric} />
                ))}
            </div>
        </div>
    </div>
)

export const NumberCard: StoryObj = {
    render: () => <UsageMetricCard metric={baseNumberMetric} />,
}

export const SparklineCard: StoryObj = {
    render: () => <UsageMetricCard metric={baseSparklineMetric} />,
}

export const PositiveAndNegativeTrends: Story = {
    render: () => (
        <Grid
            metrics={[
                baseNumberMetric,
                {
                    ...baseNumberMetric,
                    id: 'events',
                    name: 'Events',
                    value: 1_810_000_000,
                    change_from_previous_pct: 0.33,
                },
                {
                    ...baseNumberMetric,
                    id: 'recordings',
                    name: 'Recordings',
                    value: 25_400,
                    change_from_previous_pct: -0.92,
                },
                { ...baseNumberMetric, id: 'flat', name: 'Alerts', value: 12, change_from_previous_pct: 0 },
            ]}
        />
    ),
}

/**
 * Mixes number and sparkline cards in the same row at the @xl (4-col) breakpoint,
 * pinned to a width that reproduces the original regression where the
 * "Last N days" label wrapped and made sparkline tiles taller than neighbors.
 */
export const MixedGridAtNarrowBreakpoint: Story = {
    render: () => (
        <Grid
            metrics={[
                baseNumberMetric,
                {
                    ...baseNumberMetric,
                    id: 'recordings',
                    name: 'Recordings',
                    value: 25_400,
                    change_from_previous_pct: -0.92,
                },
                baseSparklineMetric,
                {
                    ...baseSparklineMetric,
                    id: 'events-with-groups',
                    name: 'Events with groups',
                    value: 563_000,
                    change_from_previous_pct: 0.11,
                    timeseries: sparklineData.slice().reverse(),
                },
            ]}
        />
    ),
}

export const LongMetricNameTruncates: StoryObj = {
    render: () => (
        <UsageMetricCard
            metric={{
                ...baseSparklineMetric,
                name: 'Extremely long feature flag evaluation requests metric name',
            }}
        />
    ),
}

export const NullTrend: StoryObj = {
    render: () => (
        <Grid
            metrics={[
                { ...baseNumberMetric, id: 'null-number', change_from_previous_pct: null },
                { ...baseSparklineMetric, id: 'null-sparkline', change_from_previous_pct: null },
            ]}
        />
    ),
}

export const Skeleton: StoryObj = {
    render: () => (
        <div style={{ width: 1280 }}>
            <UsageMetricCardSkeleton />
        </div>
    ),
    parameters: {
        testOptions: { waitForLoadersToDisappear: false },
    },
}
