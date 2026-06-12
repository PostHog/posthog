import type { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import { AnyScaleOptions, Sparkline, SparklineProps } from './Sparkline'

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
