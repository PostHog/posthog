import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { PathCleaningFilter } from '~/types'

import { PathCleanFilters, PathCleanFiltersProps } from './PathCleanFilters'
import { PathCleanFiltersTable } from './PathCleanFiltersTable'

type Story = StoryObj<typeof PathCleanFilters>
const meta: Meta<typeof PathCleanFilters> = {
    title: 'Filters/PathCleanFilters',
    component: PathCleanFilters,
}
export default meta

const Template: StoryFn<typeof PathCleanFilters> = (props: Partial<PathCleanFiltersProps>) => {
    const [filters, setFilters] = useState<PathCleaningFilter[]>([
        { alias: 'insights', regex: '/insights/w+/dashboard$' },
        { regex: '/feature_flags/d+$' },
        { alias: 'recordings' },
    ])

    return <PathCleanFilters filters={filters} setFilters={setFilters} {...props} />
}

const TableTemplate: StoryFn<typeof PathCleanFiltersTable> = (props) => {
    const [filters, setFilters] = useState<PathCleaningFilter[]>([
        { alias: 'insights', regex: '/insights/\\w+/dashboard$', order: 0 },
        { alias: 'feature-flags', regex: '/feature_flags/\\d+$', order: 1 },
        { alias: 'recordings', regex: '/replay/\\w+', order: 2 },
        { alias: '', regex: '/api/v1/.*', order: 3 }, // Empty alias example
        { alias: 'invalid', regex: '[invalid(regex', order: 4 }, // Invalid regex example
    ])

    return <PathCleanFiltersTable {...props} filters={filters} setFilters={setFilters} />
}

export const TableUI: StoryObj<typeof PathCleanFiltersTable> = {
    render: TableTemplate,
    parameters: {
        docs: {
            description: {
                story: 'New table-based interface for path cleaning filters',
            },
        },
    },
}

export const TableUIEmpty: StoryObj<typeof PathCleanFiltersTable> = {
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

export const Default: Story = Template.bind({})
Default.args = {}
