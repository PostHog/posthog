import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { FilterBar } from './FilterBar'
import { filterBarLogic } from './filterBarLogic'

const EVENT_PROPERTIES = [
    { id: '1', name: '$browser', property_type: 'String', is_numerical: false },
    { id: '2', name: '$current_url', property_type: 'String', is_numerical: false },
    { id: '3', name: '$os', property_type: 'String', is_numerical: false },
    { id: '4', name: '$browser_version', property_type: 'Numeric', is_numerical: true },
    { id: '5', name: 'plan', property_type: 'String', is_numerical: false },
]

const PERSON_PROPERTIES = [
    { id: '6', name: 'email', property_type: 'String', is_numerical: false },
    { id: '7', name: 'signed_up_at', property_type: 'DateTime', is_numerical: false },
]

const FEATURE_FLAG_PROPERTIES = [
    { id: '8', name: '$feature/new-checkout', property_type: 'String', is_numerical: false },
]

const SESSION_PROPERTIES = [
    { id: '9', name: '$entry_pathname', property_type: 'String', is_numerical: false },
    { id: '10', name: '$session_duration', property_type: 'Duration', is_numerical: true },
]

const FILTERS: AnyPropertyFilter[] = [
    { type: PropertyFilterType.Event, key: '$browser', operator: PropertyOperator.Exact, value: ['Chrome', 'Firefox'] },
    { type: PropertyFilterType.Person, key: 'email', operator: PropertyOperator.IContains, value: 'example.com' },
    { type: PropertyFilterType.Cohort, key: 'id', operator: PropertyOperator.In, value: 1, cohort_name: 'Power users' },
    { type: PropertyFilterType.Event, key: '$os', operator: PropertyOperator.IsSet, value: null },
]

type StoryArgs = { filters: AnyPropertyFilter[]; openMenu?: boolean; editIndex?: number }

function Playground({ filters: initialFilters, openMenu, editIndex }: StoryArgs): JSX.Element {
    const [filters, setFilters] = useState(initialFilters)
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
            <FilterBar pageKey="story" filters={filters} onChange={setFilters} />
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
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/property_definitions/': ({ request }) => {
                    const url = new URL(request.url)
                    const search = (url.searchParams.get('search') ?? '').toLowerCase()
                    const type = url.searchParams.get('type')
                    const flags = url.searchParams.get('is_feature_flag')
                    const source =
                        type === 'person'
                            ? PERSON_PROPERTIES
                            : flags === 'true'
                              ? FEATURE_FLAG_PROPERTIES
                              : EVENT_PROPERTIES
                    return toPaginatedResponse(source.filter((property) => property.name.includes(search)))
                },
                '/api/projects/:team_id/sessions/property_definitions/': ({ request }) => {
                    const search = (new URL(request.url).searchParams.get('search') ?? '').toLowerCase()
                    return toPaginatedResponse(SESSION_PROPERTIES.filter((property) => property.name.includes(search)))
                },
                '/api/projects/:team_id/cohorts/': toPaginatedResponse([
                    { id: 1, name: 'Power users', count: 120 },
                    { id: 2, name: 'Trial accounts', count: 48 },
                ]),
                '/api/event/values/': {
                    results: [{ name: 'Chrome' }, { name: 'Firefox' }, { name: 'Safari' }, { name: 'Edge' }],
                },
                '/api/person/values/': { results: [{ name: 'alice@example.com' }, { name: 'bob@example.com' }] },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<StoryArgs>

export const Empty: Story = { args: { filters: [] } }

export const WithFilters: Story = { args: { filters: FILTERS } }

export const FieldPicker: Story = {
    args: { filters: FILTERS.slice(0, 1), openMenu: true },
    parameters: { testOptions: { waitForSelector: 'text=Browse' } },
}

export const ValuePicker: Story = {
    args: { filters: FILTERS.slice(0, 1), editIndex: 0 },
    parameters: { testOptions: { waitForSelector: 'text=Safari' } },
}
