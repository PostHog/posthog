import React, { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { CohortSelectorField } from './CohortField'
import { CohortSelectorFieldProps, FieldOptionsType } from 'scenes/cohorts/CohortFilters/types'

export default {
    title: 'Filters/Cohort Filters/Fields/Select',
    component: CohortSelectorField,
} as ComponentMeta<typeof CohortSelectorField>

const Template: ComponentStory<typeof CohortSelectorField> = (props: CohortSelectorFieldProps) => {
    const [value, setValue] = useState<string | undefined>(
        Object.keys(props.fieldOptionGroupTypes?.[0] ?? {})?.[0] ?? null
    )
    return (
        <CohortSelectorField
            {...props}
            fieldKey="key"
            criteria={{ key: value }}
            onChange={(newCriteria) => setValue(newCriteria.key)}
        />
    )
}

export const AggregationSelector = Template.bind({})
AggregationSelector.args = {
    fieldOptionGroupTypes: [FieldOptionsType.EventAggregation, FieldOptionsType.PropertyAggregation],
    placeholder: 'Choose',
}

export const ActorsSelector = Template.bind({})
ActorsSelector.args = {
    fieldOptionGroupTypes: [FieldOptionsType.Actors],
    placeholder: 'Choose',
}

export const BehavioralSelector = Template.bind({})
BehavioralSelector.args = {
    fieldOptionGroupTypes: [
        FieldOptionsType.EventBehavioral,
        FieldOptionsType.PersonPropertyBehavioral,
        FieldOptionsType.CohortBehavioral,
        FieldOptionsType.LifecycleBehavioral,
    ],
    placeholder: 'Choose',
}

export const TimeUnitSelector = Template.bind({})
TimeUnitSelector.args = {
    fieldOptionGroupTypes: [FieldOptionsType.TimeUnits],
    placeholder: 'Choose',
}

export const DateOperatorSelector = Template.bind({})
DateOperatorSelector.args = {
    fieldOptionGroupTypes: [FieldOptionsType.DateOperators],
    placeholder: 'Choose',
}

export const MathOperatorSelector = Template.bind({})
MathOperatorSelector.args = {
    fieldOptionGroupTypes: [FieldOptionsType.MathOperators],
    placeholder: 'Choose',
}

export const ValueOptionSelector = Template.bind({})
ValueOptionSelector.args = {
    fieldOptionGroupTypes: [FieldOptionsType.ValueOptions],
    placeholder: 'Choose',
}
