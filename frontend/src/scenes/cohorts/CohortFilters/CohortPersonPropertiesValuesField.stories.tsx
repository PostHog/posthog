import { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { CohortPersonPropertiesValuesField } from './CohortField'
import { renderField } from 'scenes/cohorts/CohortFilters/constants'
import { CohortPersonPropertiesValuesFieldProps, FilterType } from 'scenes/cohorts/CohortFilters/types'
import { PropertyOperator } from '~/types'

export default {
    title: 'Filters/Cohort Filters/Fields/Person Properties',
    component: CohortPersonPropertiesValuesField,
} as ComponentMeta<typeof CohortPersonPropertiesValuesField>

const Template: ComponentStory<typeof CohortPersonPropertiesValuesField> = (
    props: CohortPersonPropertiesValuesFieldProps
) => {
    const [value, setValue] = useState<string | undefined>('Chrome')
    return renderField[FilterType.PersonPropertyValues]({
        ...props,
        criteria: { operator_value: value },
        propertyKey: '$browser',
        operator: PropertyOperator.Exact,
        onChange: (newValue) => setValue(String(newValue.operator_value ?? undefined)),
    })
}

export const Basic = Template.bind({})
Basic.args = {}
