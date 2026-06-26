import type { Meta, StoryObj } from '@storybook/react'

import type { ChartSpec } from './chartSpec'
import { ChartSpecRenderer } from './ChartSpecRenderer'

// These specs are hand-written to stand in for what an LLM would emit. They prove the rendering
// half of the gen-UI charts idea end to end, before any model is wired up.

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const WEEK_DATES = ['2026-06-15', '2026-06-16', '2026-06-17', '2026-06-18', '2026-06-19', '2026-06-20', '2026-06-21']

const comboDualAxis: ChartSpec = {
    chartType: 'combo',
    title: 'Revenue vs conversion rate',
    narrative:
        'Revenue (bars, left) climbs while conversion rate (line, right) holds steady — growth is from volume, not efficiency.',
    labels: DAYS,
    axes: [
        { id: 'left', format: 'currency', currency: 'USD', label: 'Revenue' },
        { id: 'right', format: 'percentage', label: 'Conversion' },
    ],
    series: [
        {
            key: 'revenue',
            label: 'Revenue',
            type: 'bar',
            axis: 'left',
            data: [4200, 5100, 4800, 6300, 7200, 3100, 2800],
        },
        {
            key: 'cvr',
            label: 'Conversion rate',
            type: 'line',
            axis: 'right',
            data: [3.1, 3.3, 3.0, 3.4, 3.5, 3.2, 3.1],
        },
    ],
    referenceLines: [{ value: 6000, label: 'Daily target', variant: 'goal', axis: 'left' }],
}

const stackedBar: ChartSpec = {
    chartType: 'bar',
    title: 'Signups by channel',
    labels: DAYS,
    series: [
        { key: 'organic', label: 'Organic', data: [120, 132, 101, 134, 90, 40, 35] },
        { key: 'paid', label: 'Paid', data: [60, 72, 55, 81, 66, 20, 18] },
        { key: 'referral', label: 'Referral', data: [30, 28, 41, 35, 44, 12, 10] },
    ],
    config: { stacked: true, showLegend: true, showGrid: true },
}

const horizontalRanked: ChartSpec = {
    chartType: 'bar',
    title: 'Top pages by views',
    labels: ['/home', '/pricing', '/blog', '/docs', '/signup'],
    series: [{ key: 'views', label: 'Views', data: [9200, 5400, 4800, 3100, 2200] }],
    config: { horizontal: true, grouped: true, showValueLabels: true },
    axes: [{ id: 'left', format: 'short' }],
}

const timeSeriesGoal: ChartSpec = {
    chartType: 'timeSeriesLine',
    title: 'Weekly active users',
    narrative: 'WAU is trending toward the 1k goal line, with a dip over the weekend.',
    labels: WEEK_DATES,
    series: [{ key: 'wau', label: 'WAU', fill: true, data: [820, 910, 880, 1010, 1120, 640, 590] }],
    axes: [{ id: 'left', format: 'short', startAtZero: false }],
    referenceLines: [{ value: 1000, label: 'Goal', variant: 'goal' }],
    config: { showLegend: false },
}

const donut: ChartSpec = {
    chartType: 'pie',
    title: 'Traffic by device',
    labels: ['Desktop', 'Mobile', 'Tablet'],
    series: [{ key: 'device', label: 'Device', data: [62, 31, 7] }],
    config: { donut: true },
    axes: [{ id: 'left', format: 'percentage' }],
}

const metricCard: ChartSpec = {
    chartType: 'metricCard',
    title: 'MRR',
    labels: WEEK_DATES,
    series: [{ key: 'mrr', label: 'MRR', data: [41000, 41800, 42200, 43100, 44000, 44200, 45600] }],
    axes: [{ id: 'left', format: 'currency', currency: 'USD' }],
}

const SPECS: ChartSpec[] = [comboDualAxis, stackedBar, horizontalRanked, timeSeriesGoal, donut, metricCard]

const meta: Meta<typeof ChartSpecRenderer> = {
    title: 'Components/ChartSpecRenderer',
    component: ChartSpecRenderer,
}
export default meta

type Story = StoryObj<typeof ChartSpecRenderer>

export const Gallery: Story = {
    render: () => (
        <div className="grid grid-cols-2 gap-6 max-w-[1000px]">
            {SPECS.map((spec, i) => (
                <div key={i} className="border rounded p-4 bg-surface-primary">
                    <ChartSpecRenderer spec={spec} height={260} />
                </div>
            ))}
        </div>
    ),
}

export const ComboDualAxis: Story = { render: () => <ChartSpecRenderer spec={comboDualAxis} /> }
export const StackedBar: Story = { render: () => <ChartSpecRenderer spec={stackedBar} /> }
export const HorizontalRanked: Story = { render: () => <ChartSpecRenderer spec={horizontalRanked} /> }
export const TimeSeriesWithGoal: Story = { render: () => <ChartSpecRenderer spec={timeSeriesGoal} /> }
export const Donut: Story = { render: () => <ChartSpecRenderer spec={donut} /> }
export const MetricCardStory: Story = { name: 'Metric Card', render: () => <ChartSpecRenderer spec={metricCard} /> }
