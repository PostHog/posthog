import { ComponentMeta, ComponentStory } from '@storybook/react'
import { PaginationControl, PaginationControlProps } from './PaginationControl'
import { usePagination } from './usePagination'

export default {
    title: 'Lemon UI/Pagination Control',
    component: PaginationControl,
} as ComponentMeta<typeof PaginationControl>

const DATA_SOURCE = Array(43)
    .fill(null)
    .map((_, index) => index)

const Template: ComponentStory<typeof PaginationControl> = (props: Partial<PaginationControlProps<any>>) => {
    const state = usePagination(DATA_SOURCE, { pageSize: 10 })
    return <PaginationControl {...state} {...props} />
}

export const PaginationControl_ = Template.bind({})
PaginationControl_.args = {}

export const Bordered = Template.bind({})
Bordered.args = { bordered: true }
