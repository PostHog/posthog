import type { Meta, StoryObj } from '@storybook/react'

import { useChartTheme } from 'lib/charts/hooks'

import { PagePerformanceMetricCard, PagePerformanceMetricCardProps } from './PagePerformanceMetricCard'

type StoryProps = Omit<PagePerformanceMetricCardProps, 'theme'>

const SPARKLINE = [820, 910, 760, 1180, 1040, 1320, 1290]
const SPARKLINE_LABELS = ['Aug 7', 'Aug 8', 'Aug 9', 'Aug 10', 'Aug 11', 'Aug 12', 'Aug 13']

function ThemedMetricCard(props: StoryProps): JSX.Element {
    const theme = useChartTheme()
    return (
        <div className="w-64">
            <PagePerformanceMetricCard {...props} theme={theme} color={theme.colors[0]} />
        </div>
    )
}

type Story = StoryObj<StoryProps>
const meta: Meta<StoryProps> = {
    title: 'Scenes-App/Web Analytics/PagePerformanceMetricCard',
    component: ThemedMetricCard,
    args: {
        label: 'LLM referrals',
        value: 1290,
        previous: 980,
        changeFromPreviousPct: 32,
        sparkline: SPARKLINE,
        sparklineLabels: SPARKLINE_LABELS,
        color: '',
        loading: false,
    },
}
export default meta

export const Increase: Story = {}

export const Decrease: Story = {
    args: { value: 640, previous: 980, changeFromPreviousPct: -35 },
}

export const WithoutComparison: Story = {
    args: { previous: null, changeFromPreviousPct: null },
}

export const WithoutSparkline: Story = {
    args: { sparkline: [], sparklineLabels: [] },
}

export const Loading: Story = {
    args: { loading: true },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
