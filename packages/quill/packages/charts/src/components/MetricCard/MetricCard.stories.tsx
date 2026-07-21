import { Meta, StoryObj } from '@storybook/react'

import { Stage, useReactiveTheme } from '../../story-helpers'
import { MetricCard } from './MetricCard'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const REVENUE = [4200, 5100, 4700, 5400, 6000, 5800, 6400, 6900, 7200, 7700, 8100, 8800]
const FALLING = [9800, 9200, 8600, 8400, 7700, 7300, 6900, 6500, 6000, 5400, 4800, 4200]

const meta: Meta = { title: 'Components/HogCharts/MetricCard', parameters: { layout: 'centered' } }
export default meta

type Story = StoryObj<{}>

export const Default: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={360} height={320}>
                <div className="rounded-xl border border-primary bg-surface-primary p-5 shadow-sm w-full h-full flex flex-col">
                    <MetricCard
                        title="Total Revenue"
                        data={REVENUE}
                        labels={MONTHS}
                        theme={theme}
                        color="#22d3ee"
                        sparklineClassName="mt-4 -mx-5 -mb-5"
                        formatValue={(v) => `US$${Math.round(v).toLocaleString()}`}
                    />
                </div>
            </Stage>
        )
    },
}

export const Falling: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={360} height={320}>
                <div className="rounded-xl border border-primary bg-surface-primary p-5 shadow-sm w-full h-full flex flex-col">
                    <MetricCard
                        title="Active users"
                        data={FALLING}
                        labels={MONTHS}
                        theme={theme}
                        color="#fb7185"
                        sparklineClassName="mt-4 -mx-5 -mb-5"
                        formatValue={(v) => Math.round(v).toLocaleString()}
                    />
                </div>
            </Stage>
        )
    },
}

export const NoChange: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={360} height={320}>
                <div className="rounded-xl border border-primary bg-surface-primary p-5 shadow-sm w-full h-full flex flex-col">
                    <MetricCard
                        title="Daily signups"
                        data={REVENUE}
                        labels={MONTHS}
                        theme={theme}
                        color="#22d3ee"
                        showChange={false}
                        sparklineClassName="mt-4 -mx-5 -mb-5"
                        formatValue={(v) => Math.round(v).toLocaleString()}
                    />
                </div>
            </Stage>
        )
    },
}

export const RestingSummary: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const avg = Math.round(REVENUE.reduce((a, b) => a + b, 0) / REVENUE.length)
        return (
            <Stage width={360} height={320}>
                <div className="rounded-xl border border-primary bg-surface-primary p-5 shadow-sm w-full h-full flex flex-col">
                    <MetricCard
                        title="Total Revenue"
                        value={avg}
                        restingSubtitle="Avg"
                        data={REVENUE}
                        labels={MONTHS}
                        theme={theme}
                        color="#22d3ee"
                        sparklineClassName="mt-4 -mx-5 -mb-5"
                        formatValue={(v) => `US$${Math.round(v).toLocaleString()}`}
                    />
                </div>
            </Stage>
        )
    },
}

export const IncompleteTrailingPeriod: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={360} height={320}>
                <div className="rounded-xl border border-primary bg-surface-primary p-5 shadow-sm w-full h-full flex flex-col">
                    <MetricCard
                        title="Total Revenue"
                        data={REVENUE}
                        labels={MONTHS}
                        theme={theme}
                        color="#22d3ee"
                        // Last two points are an in-progress period — dashed so it doesn't read as a real dip.
                        sparklineDashedFromIndex={REVENUE.length - 2}
                        sparklineClassName="mt-4 -mx-5 -mb-5"
                        formatValue={(v) => `US$${Math.round(v).toLocaleString()}`}
                    />
                </div>
            </Stage>
        )
    },
}

export const NumberOnly: Story = {
    render: () => (
        <Stage width={360} height={200}>
            <div className="rounded-xl border border-primary bg-surface-primary p-5 shadow-sm w-full h-full flex flex-col">
                <MetricCard
                    title="Lifetime revenue"
                    value={1_284_320}
                    change={{ value: 8.4 }}
                    formatValue={(v) => `US$${v.toLocaleString()}`}
                />
            </div>
        </Stage>
    ),
}

export const ClickableWithTooltipAndFooter: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={360} height={340}>
                <div className="rounded-xl border border-primary bg-surface-primary p-5 shadow-sm w-full h-full flex flex-col">
                    <MetricCard
                        title="Total Revenue"
                        data={REVENUE}
                        labels={MONTHS}
                        theme={theme}
                        color="#22d3ee"
                        titleTooltip="Sum of all invoices paid in the selected range."
                        onClick={() => undefined}
                        onClickTooltip="View paid invoices"
                        footer={<span className="cursor-pointer underline">View paid invoices</span>}
                        sparklineClassName="mt-4"
                        formatValue={(v) => `US$${Math.round(v).toLocaleString()}`}
                    />
                </div>
            </Stage>
        )
    },
}

export const Loading: Story = {
    render: () => (
        <Stage width={360} height={320}>
            <div className="rounded-xl border border-primary bg-surface-primary p-5 shadow-sm w-full h-full flex flex-col">
                <MetricCard title="Total Revenue" loading />
            </div>
        </Stage>
    ),
}

const EMAILS = [1800, 2100, 1950, 2400, 2600, 2500, 2800, 3000, 3100, 3300, 3500, 3800]
const PUSH = [900, 1100, 1050, 1200, 1400, 1300, 1500, 1600, 1700, 1800, 1900, 2100]

export const MultiSeries: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const total = EMAILS.reduce((a, b) => a + b, 0) + PUSH.reduce((a, b) => a + b, 0)
        return (
            <Stage width={360} height={320}>
                <div className="rounded-xl border border-primary bg-surface-primary p-5 shadow-sm w-full h-full flex flex-col">
                    <MetricCard
                        title="Messages sent"
                        value={total}
                        series={[
                            { key: 'email', label: 'Emails sent', data: EMAILS, color: '#1d4aff' },
                            { key: 'push', label: 'Push notifications sent', data: PUSH, color: '#42827e' },
                        ]}
                        labels={MONTHS}
                        theme={theme}
                        sparklineClassName="mt-4 -mx-5 -mb-5"
                        formatValue={(v) => Math.round(v).toLocaleString()}
                    />
                </div>
            </Stage>
        )
    },
}
