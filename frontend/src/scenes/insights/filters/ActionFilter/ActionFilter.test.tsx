import { MOCK_GROUP_TYPES } from '~/lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'
import { setupInsightMocks } from '~/test/insight-testing'
import { EntityTypes, FilterType, PropertyFilterType, PropertyOperator } from '~/types'

import { ActionFilter } from './ActionFilter'
import { MathAvailability } from './ActionFilterRow/types'

// CDP compiles these filters to bytecode on the backend, so the wrapper has to hand them back
// with the same field names it was given.
const CDP_FILTERS = {
    events: [
        {
            id: '$pageview',
            type: EntityTypes.EVENTS,
            name: '$pageview',
            order: 0,
            properties: [
                {
                    key: '$current_url',
                    value: 'https://example.com',
                    operator: PropertyOperator.IContains,
                    type: PropertyFilterType.Event,
                },
            ],
        },
    ],
    actions: [{ id: '9', type: EntityTypes.ACTIONS, name: 'Users signed up', order: 1, properties: [] }],
    data_warehouse: [
        {
            id: 'payments',
            type: EntityTypes.DATA_WAREHOUSE,
            name: 'payments',
            order: 2,
            table_name: 'payments',
            timestamp_field: 'created_at',
            distinct_id_field: 'person_id',
            id_field: 'id',
            properties: [],
        },
    ],
} as unknown as FilterType

describe('ActionFilter', () => {
    afterEach(cleanup)

    beforeEach(() => {
        initKeaTests()
        setupInsightMocks()
        useMocks({
            get: {
                '/api/projects/:team/actions/': { results: CDP_FILTERS.actions },
                '/api/environments/:team/groups_types/': MOCK_GROUP_TYPES,
                '/api/projects/:team/warehouse_tables/': { results: [] },
                '/api/projects/:team/warehouse_saved_queries/': { results: [] },
                '/api/projects/:team/warehouse_view_links/': { results: [] },
            },
        })
        actionsModel.mount()
        groupsModel.mount()
    })

    it.each([
        {
            defaults: 'no defaults',
            addFilterDefaultOptions: undefined,
            addedTo: 'events',
            added: { type: EntityTypes.EVENTS, id: '$pageview', order: 3 },
        },
        {
            // The project's default event in tests is $pageview, so a different id shows which one won.
            defaults: 'a legacy event default',
            addFilterDefaultOptions: {
                id: 'signed_up',
                name: 'signed_up',
                type: EntityTypes.EVENTS,
                funnel_from_step: 0,
                funnel_to_step: 1,
            },
            addedTo: 'events',
            added: {
                type: EntityTypes.EVENTS,
                id: 'signed_up',
                name: 'signed_up',
                funnel_from_step: 0,
                funnel_to_step: 1,
                order: 3,
            },
        },
        {
            defaults: 'a warehouse default',
            addFilterDefaultOptions: { type: EntityTypes.DATA_WAREHOUSE, name: 'Select a table' },
            addedTo: 'data_warehouse',
            added: { type: EntityTypes.DATA_WAREHOUSE, name: 'Select a table', order: 3 },
        },
    ] as const)(
        'hands a CDP-shaped filter object back unchanged after adding a row with $defaults',
        async ({ addFilterDefaultOptions, addedTo, added }) => {
            const setFilters = jest.fn()
            render(
                <Provider>
                    <ActionFilter
                        filters={CDP_FILTERS}
                        setFilters={setFilters}
                        typeKey="plugin-filters"
                        mathAvailability={MathAvailability.None}
                        buttonCopy="Add filter"
                        addFilterDefaultOptions={addFilterDefaultOptions}
                    />
                </Provider>
            )

            await userEvent.click(screen.getByTestId('add-action-event-button'))

            expect(setFilters).toHaveBeenCalledTimes(1)
            const expected: Record<string, unknown[]> = {
                events: [expect.objectContaining({ ...CDP_FILTERS.events![0], order: 0 })],
                actions: [expect.objectContaining({ ...CDP_FILTERS.actions![0], id: 9, order: 1 })],
                data_warehouse: [expect.objectContaining({ ...CDP_FILTERS.data_warehouse![0], order: 2 })],
            }
            expected[addedTo].push(expect.objectContaining(added))
            expect(setFilters.mock.calls[0][0]).toMatchObject(expected)
        }
    )
})
