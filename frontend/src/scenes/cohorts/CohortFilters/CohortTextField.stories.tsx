import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { renderField } from 'scenes/cohorts/CohortFilters/constants'
import { CohortTextFieldProps, FilterType } from 'scenes/cohorts/CohortFilters/types'

import { CohortTextField } from './CohortField'

type Story = StoryObj<typeof CohortTextField>
const meta: Meta<typeof CohortTextField> = {
    title: 'Filters/Cohort Filters/Fields/Text',
    component: CohortTextField,
}
export default meta

const Template: StoryFn<typeof CohortTextField> = (props: CohortTextFieldProps) => {
    return renderField[FilterType.Text]({
        ...props,
        value: 'in the last',
    })
}

export const Basic: Story = Template.bind({})
Basic.args = {}
