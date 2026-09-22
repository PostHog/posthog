import type { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import { Sparkline, SparklineProps } from './Sparkline'

type Story = StoryObj<SparklineProps>
const meta: Meta<SparklineProps> = {
    title: 'Components/Sparkline',
    component: Sparkline,
    render: (args) => <Sparkline {...args} className="w-64 h-16" />,
}
export default meta

const LABELS = ['Mon', 'Tue', 'Wed', 'Thurs', 'Fri', 'Sat', 'Sun']

export const BarChart: Story = {
    args: {
        data: [10, 5, 3, 30, 22, 10, 2],
        labels: LABELS,
    },
    // `Sparkline` now dispatches to the quill chart, whose canvas has no intrinsic size, so the
    // wrapper needs an explicit height — a bare `w-full` collapses to zero height under the runner.
    render: (args) => <Sparkline {...args} className="w-64 h-16" />,
}

export const StackedBarChart: Story = {
    args: {
        data: [
            { name: 'success', values: [10, 5, 3, 30, 22, 10, 2], color: 'success' },
            { name: 'failure', values: [1, 0, 2, 4, 0, 1, 0], color: 'danger' },
        ],
        labels: LABELS,
    },
}

export const LineChart: Story = {
    args: {
        data: [10, 5, 3, 30, 22, 10, 2],
        labels: LABELS,
        type: 'line',
        color: 'success',
    },
}

const dataRange = Array.from({ length: 50 }, (_, i) => i)
export const Timeseries: Story = {
    args: {
        data: [
            {
                name: 'occurrence',
                values: dataRange.map((i) => (i * 37) % 100),
                color: 'primitive-neutral-800',
            },
        ],
        labels: dataRange.map((i) => dayjs().subtract(i, 'day').format()),
        renderLabel: (label) => dayjs(label).format('MMM D'),
    },
}
