import { expectLogic } from 'kea-test-utils'

import { PEOPLE_LIST_CONTEXT_KEY, PEOPLE_LIST_DEFAULT_QUERY } from 'scenes/persons/personsSceneLogic'

import { useMocks } from '~/mocks/jest'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { ActorsQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { tableViewLogic } from './tableViewLogic'

const SHARED_VIEW = {
    id: '01234567-89ab-cdef-0123-456789abcdef',
    context_key: PEOPLE_LIST_CONTEXT_KEY,
    name: 'Distinct IDs',
    columns: ['person_display_name -- Person', 'pdi.distinct_id'],
    filters: [],
    order_by: [],
    visibility: 'shared',
    created_by: 4242,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
}

describe('tableViewLogic', () => {
    const defaultSelect = [...defaultDataTableColumns(NodeKind.ActorsQuery, false), 'person.$delete']
    const lastSeenAtSelect = [...defaultDataTableColumns(NodeKind.ActorsQuery, true), 'person.$delete']

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/column_configurations/': () => [200, { results: [SHARED_VIEW] }],
            },
        })
        initKeaTests()
        // `currentView` persists to localStorage, so start each case as a user who has never
        // selected a view. That is the state someone is in when a teammate created the view.
        localStorage.clear()
    })

    it.each<[string, string[], boolean]>([
        ['the untouched default query', defaultSelect, true],
        ['the default query of a team that tracks last seen at', lastSeenAtSelect, true],
        ['a query the user already changed', [...defaultSelect, 'properties.email'], false],
    ])('with %s', async (_label, select, shouldApply) => {
        const setQuery = jest.fn()
        const logic = tableViewLogic({
            contextKey: PEOPLE_LIST_CONTEXT_KEY,
            query: { ...PEOPLE_LIST_DEFAULT_QUERY.source, select } as ActorsQuery,
            setQuery,
        })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadViews()
        }).toFinishAllListeners()

        // The view is selected either way, which is what labels the dropdown button.
        expect(logic.values.currentView?.id).toEqual(SHARED_VIEW.id)

        if (shouldApply) {
            expect(setQuery).toHaveBeenCalledTimes(1)
            expect(setQuery.mock.calls[0][0].select).toEqual(SHARED_VIEW.columns)
        } else {
            expect(setQuery).not.toHaveBeenCalled()
        }
    })
})
