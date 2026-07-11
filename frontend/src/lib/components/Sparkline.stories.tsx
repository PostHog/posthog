import type { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import { AnyScaleOptions, QuillSparkline, Sparkline, SparklineProps } from './Sparkline'

type Story = StoryObj<SparklineProps>
const meta: Meta<SparklineProps> = {
    title: 'Components/Sparkline',
    component: Sparkline,
    render: (args) => {
        return <Sparkline {...args} className="w-full" />
    },
}
export default meta

export const BarChart: Story = {
    args: {
        data: [10, 5, 3, 30, 22, 10, 2],
        labels: ['Mon', 'Tue', 'Wed', 'Thurs', 'Fri', 'Sat', 'Sun'],
    },
}

const dataRange = Array.from({ length: 50 }, (_, i) => i)
export const TimeseriesChart: Story = {
    args: {
        data: [
            {
                name: 'occurrence',
                values: dataRange.map(() => Math.floor(Math.random() * 100)),
                color: 'primitive-neutral-800',
                hoverColor: 'primary-3000',
            },
        ],
        labels: dataRange.map((i) => dayjs().subtract(i, 'day').format()),
        renderLabel: (label) => dayjs(label).format('MMM D'),
        withXScale: (scale: AnyScaleOptions) => {
            return {
                ...scale,
                type: 'timeseries',
                ticks: {
                    ...scale.ticks,
                    display: true,
                    maxRotation: 0,
                    maxTicksLimit: 5,
                },
                time: {
                    unit: 'day',
                    round: 'day',
                    displayFormats: {
                        day: 'MMM D',
                    },
                },
            } as AnyScaleOptions
        },
    },
}

// Quill-rendered variants (see docs/internal/quill-migration-sparkline.md), for side-by-side
// comparison with the legacy stories above. These render `QuillSparkline` directly rather than
// flipping the `quill-sparkline` flag: the flag dispatch is unusable under Storybook, whose
// implicit-action args inject an `onSelectionChange` spy that the dispatch reads as a
// legacy-only feature. Quill charts fill their container, so an explicit height is passed.
export const BarChartQuill: Story = {
    args: {
        data: [10, 5, 3, 30, 22, 10, 2],
        labels: ['Mon', 'Tue', 'Wed', 'Thurs', 'Fri', 'Sat', 'Sun'],
    },
    render: (args) => <QuillSparkline {...args} className="w-full h-16" />,
}

export const StackedBarChartQuill: Story = {
    args: {
        data: [
            { name: 'success', values: [10, 5, 3, 30, 22, 10, 2], color: 'success' },
            { name: 'failure', values: [1, 0, 2, 4, 0, 1, 0], color: 'danger' },
        ],
        labels: ['Mon', 'Tue', 'Wed', 'Thurs', 'Fri', 'Sat', 'Sun'],
    },
    render: (args) => <QuillSparkline {...args} className="w-full h-16" />,
}

export const LineChartQuill: Story = {
    args: {
        data: [10, 5, 3, 30, 22, 10, 2],
        labels: ['Mon', 'Tue', 'Wed', 'Thurs', 'Fri', 'Sat', 'Sun'],
        type: 'line',
        color: 'success',
    },
    render: (args) => <QuillSparkline {...args} className="w-full h-16" />,
}
