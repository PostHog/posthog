import type { Meta, StoryObj } from '@storybook/react'

import { renderField } from 'scenes/cohorts/CohortFilters/constants'
import { CohortTextFieldProps, FilterType } from 'scenes/cohorts/CohortFilters/types'

import { CohortTextField } from './CohortField'

type Story = StoryObj<typeof meta>
const meta: Meta<typeof CohortTextField> = {
    title: 'Filters/Cohort Filters/Fields/Text',
    component: CohortTextField,
    render: (props: CohortTextFieldProps) => {
        return renderField[FilterType.Text]({
            ...props,
            value: 'in the last',
        })
    },
}
export default meta

export const Basic: Story = {
    args: {},
}
