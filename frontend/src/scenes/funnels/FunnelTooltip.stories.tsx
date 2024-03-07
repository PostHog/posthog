import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { FunnelStepWithConversionMetrics } from '~/types'

import { FunnelTooltip, FunnelTooltipProps } from './FunnelTooltip'

const step: FunnelStepWithConversionMetrics = {
    action_id: '$pageview',
    name: '$pageview',
    custom_name: null,
    order: 0,
    people: [],
    count: 1,
    type: 'events',
    average_conversion_time: null,
    median_conversion_time: null,
    droppedOffFromPrevious: 0,
    conversionRates: {
        fromPrevious: 1,
        total: 1,
        fromBasisStep: 1,
    },
    breakdown_value: 'Baseline',
    converted_people_url: '',
    dropped_people_url: '',
}

type Story = StoryObj<typeof FunnelTooltip>
const meta: Meta<typeof FunnelTooltip> = {
    title: 'Components/FunnelTooltip',
    component: FunnelTooltip,
    args: {
        showPersonsModal: true,
        stepIndex: 0,
        series: step,
        groupTypeLabel: 'persons',
        breakdownFilter: undefined,
    },
}
export default meta

const BasicTemplate: StoryFn<typeof FunnelTooltip> = (props: FunnelTooltipProps) => {
    return <FunnelTooltip {...props} />
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {}

export const WithLongName: Story = BasicTemplate.bind({})
WithLongName.args = {
    series: {
        ...step,
        custom_name: 'with a very very very very very very very very very very very very long custom name',
    },
}
