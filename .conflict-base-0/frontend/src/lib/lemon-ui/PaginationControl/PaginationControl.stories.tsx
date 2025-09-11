import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { PaginationControl, PaginationControlProps } from './PaginationControl'
import { usePagination } from './usePagination'

type Story = StoryObj<typeof PaginationControl>
const meta: Meta<typeof PaginationControl> = {
    title: 'Lemon UI/Pagination Control',
    component: PaginationControl,
    tags: ['autodocs'],
}
export default meta

const DATA_SOURCE = Array(43)
    .fill(null)
    .map((_, index) => index)

const Template: StoryFn<typeof PaginationControl> = (props: Partial<PaginationControlProps<any>>) => {
    const state = usePagination(DATA_SOURCE, { pageSize: 10 })
    return <PaginationControl {...state} {...props} />
}

export const PaginationControl_ = Template.bind({})
PaginationControl_.args = {}

export const Bordered: Story = Template.bind({})
Bordered.args = { bordered: true }
