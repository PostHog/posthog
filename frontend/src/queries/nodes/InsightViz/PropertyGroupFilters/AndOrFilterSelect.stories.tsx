import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { FilterLogicalOperator } from '~/types'

import { AndOrFilterSelect, AndOrFilterSelectProps } from './AndOrFilterSelect'

type Story = StoryObj<AndOrFilterSelectProps>
const meta: Meta<AndOrFilterSelectProps> = {
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
    render: (args) => {
        const [value, setValue] = useState(args.value)
        return <AndOrFilterSelect {...args} value={value} onChange={setValue} />
    },
}
export default meta

export const Default: Story = {
    args: {},
}
