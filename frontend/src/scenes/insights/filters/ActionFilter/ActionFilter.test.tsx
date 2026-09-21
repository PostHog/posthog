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

    it('hands a CDP-shaped filter object back unchanged after a UI edit', async () => {
        const setFilters = jest.fn()
        render(
            <Provider>
                <ActionFilter
                    filters={CDP_FILTERS}
                    setFilters={setFilters}
                    typeKey="plugin-filters"
                    mathAvailability={MathAvailability.None}
                    buttonCopy="Add filter"
                />
            </Provider>
        )

        await userEvent.click(screen.getByTestId('add-action-event-button'))

        expect(setFilters).toHaveBeenCalledTimes(1)
        const emitted = setFilters.mock.calls[0][0]

        expect(emitted.events).toEqual([
            expect.objectContaining({ ...CDP_FILTERS.events![0], order: 0 }),
            // the row the edit added
            expect.objectContaining({ type: EntityTypes.EVENTS, order: 3 }),
        ])
        expect(emitted.actions).toEqual([expect.objectContaining({ ...CDP_FILTERS.actions![0], id: 9, order: 1 })])
        expect(emitted.data_warehouse).toEqual([
            expect.objectContaining({ ...CDP_FILTERS.data_warehouse![0], order: 2 }),
        ])
    })
})
