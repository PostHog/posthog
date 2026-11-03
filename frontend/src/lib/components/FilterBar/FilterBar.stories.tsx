import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { AnyPropertyFilter, IntervalType, PropertyFilterType, PropertyOperator } from '~/types'

import { FilterBar } from './FilterBar'
import { FilterBarDateRange } from './FilterBarDateRange'
import { FilterBarInterval } from './FilterBarInterval'
import { filterBarLogic } from './filterBarLogic'
import { filterBarStoryDecorator } from './filterBarStoryMocks'

const FILTERS: AnyPropertyFilter[] = [
    { type: PropertyFilterType.Event, key: '$browser', operator: PropertyOperator.Exact, value: ['Chrome', 'Firefox'] },
    { type: PropertyFilterType.Person, key: 'email', operator: PropertyOperator.IContains, value: 'example.com' },
    { type: PropertyFilterType.Cohort, key: 'id', operator: PropertyOperator.In, value: 1, cohort_name: 'Power users' },
    { type: PropertyFilterType.Event, key: '$os', operator: PropertyOperator.IsSet, value: null },
]

type StoryArgs = { filters: AnyPropertyFilter[]; dateFrom?: string | null; openMenu?: boolean; editIndex?: number }

function Playground({
    filters: initialFilters,
    dateFrom: initialDateFrom = null,
    openMenu,
    editIndex,
}: StoryArgs): JSX.Element {
    const [filters, setFilters] = useState(initialFilters)
    const [interval, setInterval] = useState<IntervalType | null>(null)
    const [dates, setDates] = useState<[string | null, string | null]>([initialDateFrom, null])
    useOnMountEffect(() => {
        const logic = filterBarLogic.findMounted({ pageKey: 'story' })
        if (!logic) {
            return
        }
        if (editIndex !== undefined) {
            logic.actions.setEditingId(logic.values.items[editIndex]?.id ?? null)
            logic.actions.setMenuOpen(true)
        } else if (openMenu) {
            logic.actions.setMenuOpen(true)
        }
    })
    return (
        <div data-quill className="h-96 p-4">
            <FilterBar pageKey="story" filters={filters} onChange={setFilters}>
                <FilterBarDateRange
                    dateFrom={dates[0]}
                    dateTo={dates[1]}
                    onChange={(dateFrom, dateTo) => setDates([dateFrom, dateTo])}
                />
                <FilterBarInterval value={interval} onChange={setInterval} />
            </FilterBar>
        </div>
    )
}

const meta: Meta<StoryArgs> = {
    title: 'Filters/FilterBar',
    parameters: {
        layout: 'fullscreen',
        mockDate: '2025-10-10T12:00:00Z',
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV],
    },
    render: (args) => <Playground {...args} />,
    decorators: [filterBarStoryDecorator],
}
export default meta

type Story = StoryObj<StoryArgs>

export const Empty: Story = { args: { filters: [] } }

export const WithFilters: Story = { args: { filters: FILTERS, dateFrom: '-30d' } }

export const FieldPicker: Story = {
    args: { filters: FILTERS.slice(0, 1), openMenu: true },
    parameters: { testOptions: { waitForSelector: 'text=Browse' } },
}

export const ValuePicker: Story = {
    args: { filters: FILTERS.slice(0, 1), editIndex: 0 },
    parameters: { testOptions: { waitForSelector: 'text=Safari' } },
}
