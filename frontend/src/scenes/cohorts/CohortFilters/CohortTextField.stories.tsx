import { ComponentMeta, ComponentStory } from '@storybook/react'
import { CohortTextField } from './CohortField'
import { renderField } from 'scenes/cohorts/CohortFilters/constants'
import { CohortTextFieldProps, FilterType } from 'scenes/cohorts/CohortFilters/types'

export default {
    title: 'Filters/Cohort Filters/Fields/Text',
    component: CohortTextField,
} as ComponentMeta<typeof CohortTextField>

const Template: ComponentStory<typeof CohortTextField> = (props: CohortTextFieldProps) => {
    return renderField[FilterType.Text]({
        ...props,
        value: 'in the last',
    })
}

export const Basic = Template.bind({})
Basic.args = {}
