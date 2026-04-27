import type { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useState } from 'react'

import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'
import { renderField } from 'scenes/cohorts/CohortFilters/constants'
import { CohortNumberFieldProps, FilterType } from 'scenes/cohorts/CohortFilters/types'

import { CohortNumberField } from './CohortField'

type Story = StoryObj<CohortNumberFieldProps>
const meta: Meta<CohortNumberFieldProps> = {
    title: 'Filters/Cohort Filters/Fields/Number',
    component: CohortNumberField,
    render: (props) => {
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
    },
}
export default meta

export const Basic: Story = {
    args: {},
}
