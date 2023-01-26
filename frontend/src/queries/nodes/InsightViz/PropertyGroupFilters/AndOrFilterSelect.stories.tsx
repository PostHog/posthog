import { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { FilterLogicalOperator } from '~/types'

import { AndOrFilterSelect } from './AndOrFilterSelect'

export default {
    title: 'Filters/PropertyGroupFilters (Data Exploration)/AndOrFilterSelect',
    component: AndOrFilterSelect,
    argTypes: {
        prefix: {
            control: { type: 'text' },
        },
        suffix: {
            control: { type: 'text' },
        },
    },
    args: {
        value: FilterLogicalOperator.And,
    },
    parameters: {
        chromatic: { disableSnapshot: false },
    },
} as ComponentMeta<typeof AndOrFilterSelect>

const Template: ComponentStory<typeof AndOrFilterSelect> = (args) => {
    const [value, setValue] = useState(args.value)
    return <AndOrFilterSelect {...args} value={value} onChange={setValue} />
}

export const Default = Template.bind({})
