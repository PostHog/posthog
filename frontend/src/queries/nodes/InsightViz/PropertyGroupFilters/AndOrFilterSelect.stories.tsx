import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { FilterLogicalOperator } from '~/types'

import { AndOrFilterSelect } from './AndOrFilterSelect'

type Story = StoryObj<typeof AndOrFilterSelect>
const meta: Meta<typeof AndOrFilterSelect> = {
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
}
export default meta

const Template: StoryFn<typeof AndOrFilterSelect> = (args) => {
    const [value, setValue] = useState(args.value)
    return <AndOrFilterSelect {...args} value={value} onChange={setValue} />
}

export const Default: Story = Template.bind({})
