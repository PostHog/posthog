import type { Meta, StoryObj } from '@storybook/react'

import { PaginationControl, PaginationControlProps } from './PaginationControl'
import { usePagination } from './usePagination'

type Story = StoryObj<PaginationControlProps<any>>
const meta: Meta<PaginationControlProps<any>> = {
    title: 'Lemon UI/Pagination Control',
    component: PaginationControl as any,
    tags: ['autodocs'],
    render: (props) => {
        const DATA_SOURCE = Array(43)
            .fill(null)
            .map((_, index) => index)
        const state = usePagination(DATA_SOURCE, { pageSize: 10 })
        return <PaginationControl {...state} {...props} />
    },
}
export default meta

export const PaginationControl_: Story = {
    args: {},
}

export const Bordered: Story = {
    args: { bordered: true },
}
