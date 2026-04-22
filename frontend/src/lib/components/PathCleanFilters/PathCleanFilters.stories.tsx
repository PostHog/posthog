import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { PathCleaningFilter } from '~/types'

import { PathCleanFilters, PathCleanFiltersProps } from './PathCleanFilters'
import { PathCleanFiltersTable, PathCleanFiltersTableProps } from './PathCleanFiltersTable'

type Story = StoryObj<PathCleanFiltersProps>
const meta: Meta<PathCleanFiltersProps> = {
    title: 'Filters/PathCleanFilters',
    component: PathCleanFilters,
    render: (props) => {
        const [filters, setFilters] = useState<PathCleaningFilter[]>([
            { alias: 'insights', regex: '/insights/w+/dashboard$' },
            { regex: '/feature_flags/d+$' },
            { alias: 'recordings' },
        ])

        return <PathCleanFilters {...props} filters={filters} setFilters={setFilters} />
    },
}
export default meta

const TableTemplate = (props: PathCleanFiltersTableProps): JSX.Element => {
    const [filters, setFilters] = useState<PathCleaningFilter[]>([
        { alias: 'insights', regex: '/insights/\\w+/dashboard$', order: 0 },
        { alias: 'feature-flags', regex: '/feature_flags/\\d+$', order: 1 },
        { alias: 'recordings', regex: '/replay/\\w+', order: 2 },
        { alias: '', regex: '/api/v1/.*', order: 3 }, // Empty alias example
        { alias: 'invalid', regex: '[invalid(regex', order: 4 }, // Invalid regex example
    ])

    return <PathCleanFiltersTable {...props} filters={filters} setFilters={setFilters} />
}

export const TableUI: StoryObj<PathCleanFiltersTableProps> = {
    render: TableTemplate,
    parameters: {
        docs: {
            description: {
                story: 'New table-based interface for path cleaning filters',
            },
        },
    },
}

export const TableUIEmpty: StoryObj<PathCleanFiltersTableProps> = {
    render: () => {
        const [filters, setFilters] = useState<PathCleaningFilter[]>([])
        return <PathCleanFiltersTable filters={filters} setFilters={setFilters} />
    },
    parameters: {
        docs: {
            description: {
                story: 'Empty state when no path cleaning rules are configured.',
            },
        },
    },
}

export const Default: Story = {
    args: {},
}
