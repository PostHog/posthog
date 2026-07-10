import type { Meta, StoryObj } from '@storybook/react'
import * as React from 'react'

import { useChartTheme } from '@posthog/quill-charts'
import { Card, TooltipProvider } from '@posthog/quill-primitives'

import { Metric, MetricDelta, MetricHeader, MetricSparkline, MetricSubtitle, MetricTitle, MetricValue } from './metric'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const REVENUE = [4200, 5100, 4700, 5400, 6000, 5800, 6400, 6900, 7200, 7700, 8100, 8800]
const FALLING = [9800, 9200, 8600, 8400, 7700, 7300, 6900, 6500, 6000, 5400, 4800, 4200]

const meta: Meta = {
    title: 'Components/Metric',
    parameters: { layout: 'centered' },
    decorators: [
        (Story) => (
            <TooltipProvider>
                <Story />
            </TooltipProvider>
        ),
    ],
}
export default meta

type Story = StoryObj<{}>

// `Metric` is content, not a surface — wrap it in `<Card flush>` for the border. `flush` drops the
// card's bottom padding so a `MetricSparkline` reaches the bottom edge.
export const Default: Story = {
    render: () => {
        const theme = useChartTheme()
        return (
            <Card flush className="h-[320px] w-[360px]">
                <Metric
                    data={REVENUE}
                    labels={MONTHS}
                    theme={theme}
                    color="#22d3ee"
                    sparklineFill
                    formatValue={(v) => `US$${Math.round(v).toLocaleString()}`}
                >
                    <MetricHeader>
                        <MetricTitle>Total revenue</MetricTitle>
                        <MetricDelta />
                    </MetricHeader>
                    <MetricValue className="mt-2" />
                    <MetricSubtitle className="mt-1" />
                    <MetricSparkline />
                </Metric>
            </Card>
        )
    },
}

// Default (no `sparklineFill`): the fixed-height sparkline drops to the bottom of the card on its own
// via the part's built-in `mt-auto`.
export const Falling: Story = {
    render: () => {
        const theme = useChartTheme()
        return (
            <Card flush className="h-[320px] w-[360px]">
                <Metric
                    data={FALLING}
                    labels={MONTHS}
                    theme={theme}
                    color="#fb7185"
                    formatValue={(v) => Math.round(v).toLocaleString()}
                >
                    <MetricHeader>
                        <MetricTitle>Active users</MetricTitle>
                        <MetricDelta />
                    </MetricHeader>
                    <MetricValue className="mt-2" />
                    <MetricSubtitle className="mt-1" />
                    <MetricSparkline />
                </Metric>
            </Card>
        )
    },
}

// Composition: drop the change pill beside the headline, omit the subtitle.
export const InlineChangeNoSubtitle: Story = {
    render: () => {
        const theme = useChartTheme()
        return (
            <Card flush className="h-[320px] w-[360px]">
                <Metric
                    data={REVENUE}
                    labels={MONTHS}
                    theme={theme}
                    color="#22d3ee"
                    sparklineFill
                    formatValue={(v) => `US$${Math.round(v).toLocaleString()}`}
                >
                    <MetricTitle>Total revenue</MetricTitle>
                    <div className="mt-2 flex items-center justify-between gap-2">
                        <MetricValue />
                        <MetricDelta />
                    </div>
                    <MetricSparkline />
                </Metric>
            </Card>
        )
    },
}

export const NumberOnly: Story = {
    render: () => (
        <Card className="w-[360px]">
            <Metric value={1_284_320} change={{ value: 8.4 }} formatValue={(v) => `US$${v.toLocaleString()}`}>
                <MetricHeader>
                    <MetricTitle>Lifetime revenue</MetricTitle>
                    <MetricDelta />
                </MetricHeader>
                <MetricValue className="mt-2" />
            </Metric>
        </Card>
    ),
}

// No title row — just the headline over a bottom-anchored sparkline.
export const NoTitle: Story = {
    render: () => {
        const theme = useChartTheme()
        return (
            <Card flush className="h-[240px] w-[360px]">
                <Metric
                    data={REVENUE}
                    labels={MONTHS}
                    theme={theme}
                    color="#22d3ee"
                    formatValue={(v) => `US$${Math.round(v).toLocaleString()}`}
                >
                    <MetricValue />
                    <MetricSparkline />
                </Metric>
            </Card>
        )
    },
}

// A summary `value` (the average) with `restingSubtitle="Avg"`: at rest the headline reads as the
// average; hovering a point swaps in that point's value and month label.
export const RestingSummary: Story = {
    render: () => {
        const theme = useChartTheme()
        const avg = Math.round(REVENUE.reduce((a, b) => a + b, 0) / REVENUE.length)
        return (
            <Card flush className="h-[320px] w-[360px]">
                <Metric
                    value={avg}
                    restingSubtitle="Avg"
                    data={REVENUE}
                    labels={MONTHS}
                    theme={theme}
                    color="#22d3ee"
                    sparklineFill
                    formatValue={(v) => `US$${Math.round(v).toLocaleString()}`}
                >
                    <MetricHeader>
                        <MetricTitle>Total revenue</MetricTitle>
                        <MetricDelta />
                    </MetricHeader>
                    <MetricValue className="mt-2" />
                    <MetricSubtitle className="mt-1" />
                    <MetricSparkline />
                </Metric>
            </Card>
        )
    },
}

// `changeTooltip` spells out the comparison on hover (needs a `TooltipProvider` at the app root —
// supplied here by the story decorator).
export const WithTooltip: Story = {
    render: () => (
        <Card className="w-[360px]">
            <Metric
                value={1_284_320}
                change={{ value: 8.4 }}
                changeTooltip="vs. the previous 30 days"
                formatValue={(v) => `US$${v.toLocaleString()}`}
            >
                <MetricHeader>
                    <MetricTitle>Lifetime revenue</MetricTitle>
                    <MetricDelta />
                </MetricHeader>
                <MetricValue className="mt-2" />
            </Metric>
        </Card>
    ),
}

// `hoverChangeFromPreviousPoint`: the resting pill shows the supplied `change`; while hovering, it
// swaps to the hovered point's change vs the previous point (hidden at the first point).
export const HoverChangeFromPrevious: Story = {
    render: () => {
        const theme = useChartTheme()
        return (
            <Card flush className="h-[320px] w-[360px]">
                <Metric
                    data={FALLING}
                    labels={MONTHS}
                    theme={theme}
                    color="#fb7185"
                    change={{ value: -57.1 }}
                    hoverChangeFromPreviousPoint
                    sparklineFill
                    formatValue={(v) => Math.round(v).toLocaleString()}
                >
                    <MetricHeader>
                        <MetricTitle>Active users</MetricTitle>
                        <MetricDelta />
                    </MetricHeader>
                    <MetricValue className="mt-2" />
                    <MetricSubtitle className="mt-1" />
                    <MetricSparkline />
                </Metric>
            </Card>
        )
    },
}

// A dashboard stat grid — each tile a `<Card flush>` wrapping a `Metric` with its own bottom-anchored
// sparkline. The pill falls back to each series' own trend; `goodDirection="down"` flips churn's color.
export const Grid: Story = {
    render: () => {
        const theme = useChartTheme()
        const SIGNUPS = [180, 210, 240, 230, 260, 300, 320, 360, 400, 420, 460, 510]
        const tiles = [
            {
                title: 'Revenue',
                data: REVENUE,
                color: '#22d3ee',
                good: 'up' as const,
                format: (v: number) => `US$${Math.round(v).toLocaleString()}`,
            },
            {
                title: 'Signups',
                data: SIGNUPS,
                color: '#a78bfa',
                good: 'up' as const,
                format: (v: number) => Math.round(v).toLocaleString(),
            },
            {
                title: 'Churn',
                data: FALLING,
                color: '#fb7185',
                good: 'down' as const,
                format: (v: number) => Math.round(v).toLocaleString(),
            },
        ]
        return (
            <div className="grid w-[720px] grid-cols-3 gap-4">
                {tiles.map((t) => (
                    <Card key={t.title} flush className="h-40">
                        <Metric
                            data={t.data}
                            labels={MONTHS}
                            theme={theme}
                            color={t.color}
                            goodDirection={t.good}
                            sparklineFill
                            formatValue={t.format}
                        >
                            <MetricHeader>
                                <MetricTitle>{t.title}</MetricTitle>
                                <MetricDelta />
                            </MetricHeader>
                            <MetricValue className="mt-2 text-2xl" />
                            <MetricSparkline />
                        </Metric>
                    </Card>
                ))}
            </div>
        )
    },
}

// The same grid without sparklines — compact number-only tiles in shorter cards.
export const GridNoSparkline: Story = {
    render: () => {
        const tiles = [
            { title: 'Revenue', value: 1_284_320, change: 8.4, format: (v: number) => `US$${v.toLocaleString()}` },
            { title: 'Signups', value: 4218, change: 2.1, format: (v: number) => v.toLocaleString() },
            { title: 'Churn', value: 312, change: -4.7, format: (v: number) => v.toLocaleString() },
        ]
        return (
            <div className="grid w-[720px] grid-cols-3 gap-4">
                {tiles.map((t) => (
                    <Card key={t.title}>
                        <Metric
                            value={t.value}
                            change={{ value: t.change }}
                            goodDirection={t.title === 'Churn' ? 'down' : 'up'}
                            formatValue={t.format}
                        >
                            <MetricHeader>
                                <MetricTitle>{t.title}</MetricTitle>
                                <MetricDelta />
                            </MetricHeader>
                            <MetricValue className="mt-2 text-2xl" />
                        </Metric>
                    </Card>
                ))}
            </div>
        )
    },
}

// The metric insight's layout: no title, an inline `size="md"` pill beside the headline, and
// user-configured `positiveColor`/`negativeColor` overriding the Badge variants.
export const InsightLayout: Story = {
    render: () => {
        const theme = useChartTheme()
        const total = REVENUE.reduce((a, b) => a + b, 0)
        return (
            <Card flush className="h-[320px] w-[360px]">
                <Metric
                    value={total}
                    data={REVENUE}
                    labels={MONTHS}
                    theme={theme}
                    color="#8b5cf6"
                    change={{ value: 12.4 }}
                    changeTooltip="Comparing this period's total to the previous period's total."
                    hoverChangeFromPreviousPoint
                    positiveColor={{ background: 'rgb(139 92 246 / 10%)', foreground: '#8b5cf6' }}
                    negativeColor={{ background: 'rgb(219 55 7 / 10%)', foreground: '#db3707' }}
                    restingSubtitle="Total"
                    sparklineFill
                    formatValue={(v) => `US$${Math.round(v).toLocaleString()}`}
                >
                    <div className="flex items-center justify-between gap-2">
                        <MetricValue />
                        <MetricDelta size="md" />
                    </div>
                    <MetricSubtitle className="mt-1" />
                    <MetricSparkline />
                </Metric>
            </Card>
        )
    },
}
