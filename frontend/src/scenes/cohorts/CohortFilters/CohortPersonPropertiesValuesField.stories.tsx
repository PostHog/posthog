import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { renderField } from 'scenes/cohorts/CohortFilters/constants'
import { CohortPersonPropertiesValuesFieldProps, FilterType } from 'scenes/cohorts/CohortFilters/types'

import { PropertyOperator } from '~/types'

import { CohortPersonPropertiesValuesField } from './CohortField'

type Story = StoryObj<typeof CohortPersonPropertiesValuesField>
const meta: Meta<typeof CohortPersonPropertiesValuesField> = {
    title: 'Filters/Cohort Filters/Fields/Person Properties',
    component: CohortPersonPropertiesValuesField,
}
export default meta

const Template: StoryFn<typeof CohortPersonPropertiesValuesField> = (props: CohortPersonPropertiesValuesFieldProps) => {
    const [value, setValue] = useState<string | undefined>('Chrome')
    const PersonPropertyValuesComponent = renderField[FilterType.PersonPropertyValues]
    return (
        <div className="*:w-80">
            <PersonPropertyValuesComponent
                {...props}
                criteria={{ operator_value: value }}
                propertyKey="$browser"
                operator={PropertyOperator.Exact}
                onChange={(newValue) => setValue(String(newValue.operator_value ?? undefined))}
            />
        </div>
    )
}

export const Basic: Story = Template.bind({})
Basic.args = {}
