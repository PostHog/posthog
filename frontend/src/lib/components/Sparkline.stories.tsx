import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import { AnyScaleOptions, Sparkline } from './Sparkline'

type Story = StoryObj<typeof Sparkline>
const meta: Meta<typeof Sparkline> = {
    title: 'Components/Sparkline',
    component: Sparkline,
}
export default meta

const Template: StoryFn<typeof Sparkline> = (args) => {
    return <Sparkline {...args} className="w-full" />
}

export const BarChart: Story = Template.bind({})
BarChart.args = {
    data: [10, 5, 3, 30, 22, 10, 2],
    labels: ['Mon', 'Tue', 'Wed', 'Thurs', 'Fri', 'Sat', 'Sun'],
}

const dataRange = Array.from({ length: 50 }, (_, i) => i)
export const TimeseriesChart: Story = Template.bind({})
TimeseriesChart.args = {
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
}
