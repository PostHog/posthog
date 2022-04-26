import React, { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { CohortSelector, CohortSelectorProps } from './CohortSelectors'
import { LemonSelectOptions } from 'lib/components/LemonSelect'
import { FilterGroupTypes } from 'scenes/cohorts/CohortFilters/types'

export default {
    title: 'Filters/Cohort Filters',
    component: CohortSelector,
} as ComponentMeta<typeof CohortSelector>

const Template: ComponentStory<typeof CohortSelector> = (props: CohortSelectorProps) => {
    const [value, setValue] = useState<keyof LemonSelectOptions | null>(
        Object.keys(props.groupTypes?.[0] ?? {})?.[0] ?? null
    )
    return <CohortSelector {...props} value={value} onChange={(key) => setValue(key)} />
}

export const AggregationSelector = Template.bind({})
AggregationSelector.args = {
    groupTypes: [FilterGroupTypes.EventAggregation, FilterGroupTypes.PropertyAggregation],
    placeholder: 'Choose',
}

export const ActorsSelector = Template.bind({})
ActorsSelector.args = {
    groupTypes: [FilterGroupTypes.Actors],
    placeholder: 'Choose',
}

export const BehavioralSelector = Template.bind({})
BehavioralSelector.args = {
    groupTypes: [
        FilterGroupTypes.EventBehavioral,
        FilterGroupTypes.CohortBehavioral,
        FilterGroupTypes.LifecycleBehavioral,
    ],
    placeholder: 'Choose',
}

export const TimeUnitSelector = Template.bind({})
TimeUnitSelector.args = {
    groupTypes: [FilterGroupTypes.TimeUnits],
    placeholder: 'Choose',
}

export const DateOperatorSelector = Template.bind({})
DateOperatorSelector.args = {
    groupTypes: [FilterGroupTypes.DateOperators],
    placeholder: 'Choose',
}

export const OperatorSelector = Template.bind({})
OperatorSelector.args = {
    groupTypes: [FilterGroupTypes.Operators],
    placeholder: 'Choose',
}

export const ValueOptionSelector = Template.bind({})
ValueOptionSelector.args = {
    groupTypes: [FilterGroupTypes.ValueOptions],
    placeholder: 'Choose',
}
