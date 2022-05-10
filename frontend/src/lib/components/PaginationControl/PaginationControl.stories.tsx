import React from 'react'
import { ComponentMeta } from '@storybook/react'
import { PaginationControl } from './PaginationControl'
import { usePagination } from './usePagination'

export default {
    title: 'Lemon UI/Pagination Control',
    component: PaginationControl,
} as ComponentMeta<typeof PaginationControl>

const DATA_SOURCE = Array(43)
    .fill(null)
    .map((_, index) => index)

export function PaginationControl_(): JSX.Element {
    const state = usePagination(DATA_SOURCE, { pageSize: 10 })

    return <PaginationControl {...state} />
}
