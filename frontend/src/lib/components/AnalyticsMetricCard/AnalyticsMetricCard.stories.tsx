import type { Meta, StoryObj } from '@storybook/react'

import { useChartTheme } from 'lib/charts/hooks'

import { AnalyticsMetricCard } from './AnalyticsMetricCard'

const meta: Meta<typeof AnalyticsMetricCard> = {
    title: 'Components/Analytics Metric Card',
    component: AnalyticsMetricCard,
    parameters: { layout: 'padded' },
    args: { title: 'Active users', value: 12450, change: { value: 12.4 }, subtitle: 'vs. 11,076 prior' },
}
export default meta

type Story = StoryObj<typeof AnalyticsMetricCard>
export const Static: Story = {}
export const Clickable: Story = { args: { onClick: () => {}, ariaLabel: 'Active users' } }
export const Selected: Story = { args: { onClick: () => {}, selected: true } }
export const WithoutComparison: Story = { args: { showChange: false, subtitle: 'For selected period' } }
export const Loading: Story = {
    args: { loading: true },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const Error: Story = { args: { error: 'Could not load' } }
export const Empty: Story = { args: { value: undefined } }

export const WithTrendLine: Story = {
    render: function Render(args) {
        const theme = useChartTheme()
        return (
            <AnalyticsMetricCard
                {...args}
                theme={theme}
                data={[9100, 10400, 9800, 11100, 12450]}
                labels={['Mon', 'Tue', 'Wed', 'Thu', 'Fri']}
            />
        )
    },
}
