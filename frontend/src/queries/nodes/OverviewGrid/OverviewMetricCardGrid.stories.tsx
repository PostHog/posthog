import { Meta, StoryObj } from '@storybook/react'

import { labelFromKey } from '~/queries/nodes/WebOverview/WebOverview'

import { OverviewMetricCardGrid, OverviewMetricCardItem } from './OverviewMetricCardGrid'

type Story = StoryObj<typeof OverviewMetricCardGrid>

const meta: Meta<typeof OverviewMetricCardGrid> = {
    title: 'Web Analytics/Overview Metric Cards',
    component: OverviewMetricCardGrid,
    parameters: { layout: 'padded' },
    args: {
        loading: false,
        numSkeletons: 5,
        labelFromKey,
    },
}
export default meta

const overviewItems: OverviewMetricCardItem[] = [
    { key: 'visitors', value: 171861, previous: 160000, changeFromPreviousPct: 12, kind: 'unit' },
    { key: 'views', value: 4863551, previous: 4700000, changeFromPreviousPct: 16, kind: 'unit' },
    { key: 'sessions', value: 547323, previous: 552000, changeFromPreviousPct: -1, kind: 'unit' },
    { key: 'session duration', value: 724.92, previous: 724, changeFromPreviousPct: 0, kind: 'duration_s' },
    {
        key: 'bounce rate',
        value: 9.92,
        previous: 10,
        changeFromPreviousPct: -1,
        kind: 'percentage',
        isIncreaseBad: true,
    },
]

const conversionGoalItems: OverviewMetricCardItem[] = [
    { key: 'visitors', value: 171861, previous: 160000, changeFromPreviousPct: 12, kind: 'unit' },
    { key: 'total conversions', value: 24310, previous: 21000, changeFromPreviousPct: 16, kind: 'unit' },
    { key: 'unique conversions', value: 18402, previous: 17900, changeFromPreviousPct: 3, kind: 'unit' },
    { key: 'conversion rate', value: 10.71, previous: 11.2, changeFromPreviousPct: -4, kind: 'percentage' },
]

export const Default: Story = {
    args: { items: overviewItems },
}

export const Loading: Story = {
    args: { items: [], loading: true },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}

export const ConversionGoal: Story = {
    args: { items: conversionGoalItems, numSkeletons: 4 },
}

export const WithoutComparison: Story = {
    args: {
        items: overviewItems.map(({ previous, changeFromPreviousPct, ...rest }) => rest),
    },
}

export const WithWarning: Story = {
    args: {
        items: overviewItems.map((item) =>
            item.key === 'visitors'
                ? {
                      ...item,
                      warning:
                          'Visitors counts may be underreported. Set up a reverse proxy so that events are less likely to be intercepted by tracking blockers.',
                      warningLink: 'https://posthog.com/docs/advanced/proxy',
                  }
                : item
        ),
    },
}
