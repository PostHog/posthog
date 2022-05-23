import { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { CohortNumberField } from './CohortField'
import { renderField } from 'scenes/cohorts/CohortFilters/constants'
import { CohortNumberFieldProps, FilterType } from 'scenes/cohorts/CohortFilters/types'
import { useMountedLogic } from 'kea'
import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'

export default {
    title: 'Filters/Cohort Filters/Fields/Number',
    component: CohortNumberField,
} as ComponentMeta<typeof CohortNumberField>

const Template: ComponentStory<typeof CohortNumberField> = (props: CohortNumberFieldProps) => {
    useMountedLogic(cohortEditLogic({ id: 1 }))
    const [value, setValue] = useState<number>(30)
    return renderField[FilterType.Number]({
        ...props,
        fieldKey: 'time_value',
        criteria: {
            time_value: value,
        },
        onChange: (key) => setValue(Number(key)),
    })
}

export const Basic = Template.bind({})
Basic.args = {}
