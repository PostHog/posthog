import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { DateFilter, DateFilterProps } from './DateFilter'

type Story = StoryObj<typeof DateFilter>
const meta: Meta<typeof DateFilter> = {
    title: 'Lemon UI/Date Filter',
    component: DateFilter,
    parameters: {
        mockDate: '2023-01-26',
    },
    tags: ['autodocs'],
}
export default meta

const BasicTemplate: StoryFn<typeof DateFilter> = (props: DateFilterProps) => {
    return <DateFilter {...props} />
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {}
