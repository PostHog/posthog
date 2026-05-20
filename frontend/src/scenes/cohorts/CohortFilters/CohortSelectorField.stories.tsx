import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { CohortSelectorFieldProps, FieldOptionsType } from 'scenes/cohorts/CohortFilters/types'

import { CohortSelectorField } from './CohortField'

type Story = StoryObj<CohortSelectorFieldProps>
const meta: Meta<CohortSelectorFieldProps> = {
    title: 'Filters/Cohort Filters/Fields/Select',
    component: CohortSelectorField,
    render: (props) => {
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
    },
}
export default meta

export const AggregationSelector: Story = {
    args: {
        fieldOptionGroupTypes: [FieldOptionsType.EventAggregation, FieldOptionsType.PropertyAggregation],
        placeholder: 'Choose',
    },
}

export const ActorsSelector: Story = {
    args: {
        fieldOptionGroupTypes: [FieldOptionsType.Actors],
        placeholder: 'Choose',
    },
}

export const BehavioralSelector: Story = {
    args: {
        fieldOptionGroupTypes: [
            FieldOptionsType.EventBehavioral,
            FieldOptionsType.PersonPropertyBehavioral,
            FieldOptionsType.CohortBehavioral,
            FieldOptionsType.LifecycleBehavioral,
        ],
        placeholder: 'Choose',
    },
}

export const TimeUnitSelector: Story = {
    args: {
        fieldOptionGroupTypes: [FieldOptionsType.TimeUnits],
        placeholder: 'Choose',
    },
}

export const DateOperatorSelector: Story = {
    args: {
        fieldOptionGroupTypes: [FieldOptionsType.DateOperators],
        placeholder: 'Choose',
    },
}

export const MathOperatorSelector: Story = {
    args: {
        fieldOptionGroupTypes: [FieldOptionsType.MathOperators],
        placeholder: 'Choose',
    },
}

export const ValueOptionSelector: Story = {
    args: {
        fieldOptionGroupTypes: [FieldOptionsType.ValueOptions],
        placeholder: 'Choose',
    },
}
