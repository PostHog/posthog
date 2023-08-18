import { useState } from 'react'
import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { CohortSelectorField } from './CohortField'
import { CohortSelectorFieldProps, FieldOptionsType } from 'scenes/cohorts/CohortFilters/types'

type Story = StoryObj<typeof CohortSelectorField>
const meta: Meta<typeof CohortSelectorField> = {
    title: 'Filters/Cohort Filters/Fields/Select',
    component: CohortSelectorField,
}
export default meta

const Template: StoryFn<typeof CohortSelectorField> = (props: CohortSelectorFieldProps) => {
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

export const AggregationSelector: Story = {
    render: Template,

    args: {
        fieldOptionGroupTypes: [FieldOptionsType.EventAggregation, FieldOptionsType.PropertyAggregation],
        placeholder: 'Choose',
    },
}

export const ActorsSelector: Story = {
    render: Template,

    args: {
        fieldOptionGroupTypes: [FieldOptionsType.Actors],
        placeholder: 'Choose',
    },
}

export const BehavioralSelector: Story = {
    render: Template,

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
    render: Template,

    args: {
        fieldOptionGroupTypes: [FieldOptionsType.TimeUnits],
        placeholder: 'Choose',
    },
}

export const DateOperatorSelector: Story = {
    render: Template,

    args: {
        fieldOptionGroupTypes: [FieldOptionsType.DateOperators],
        placeholder: 'Choose',
    },
}

export const MathOperatorSelector: Story = {
    render: Template,

    args: {
        fieldOptionGroupTypes: [FieldOptionsType.MathOperators],
        placeholder: 'Choose',
    },
}

export const ValueOptionSelector: Story = {
    render: Template,

    args: {
        fieldOptionGroupTypes: [FieldOptionsType.ValueOptions],
        placeholder: 'Choose',
    },
}
