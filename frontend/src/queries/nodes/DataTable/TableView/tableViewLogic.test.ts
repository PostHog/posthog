import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { ActorsQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { PEOPLE_LIST_CONTEXT_KEY, PEOPLE_LIST_DEFAULT_QUERY } from 'products/persons/frontend/logics/personsSceneLogic'

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

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/column_configurations/': () => [200, { results: [SHARED_VIEW] }],
            },
        })
        initKeaTests()
        // Start each case as a browser that never picked a view, which is where a teammate is
        // when someone else created the view.
        localStorage.clear()
    })

    // `currentView` persists per team and context, so a test seeds it the way a browser that
    // already picked a view would have it.
    const persistSelection = (view: typeof SHARED_VIEW): void => {
        localStorage.setItem(
            `queries.nodes.DataTable.TableView.tableViewLogic.${MOCK_TEAM_ID}.${PEOPLE_LIST_CONTEXT_KEY}.currentView`,
            JSON.stringify(view)
        )
    }

    const mountLogic = (select: string[]): { logic: ReturnType<typeof tableViewLogic.build>; setQuery: jest.Mock } => {
        const setQuery = jest.fn()
        const logic = tableViewLogic({
            contextKey: PEOPLE_LIST_CONTEXT_KEY,
            query: { ...PEOPLE_LIST_DEFAULT_QUERY.source, select } as ActorsQuery,
            setQuery,
        })
        logic.mount()
        return { logic, setQuery }
    }

    it('leaves the table and the selection alone when this user never picked a view', async () => {
        const { logic, setQuery } = mountLogic(defaultSelect)

        await expectLogic(logic, () => {
            logic.actions.loadViews()
        }).toFinishAllListeners()

        expect(logic.values.views.map((view) => view.id)).toEqual([SHARED_VIEW.id])
        expect(logic.values.currentView).toBeNull()
        expect(setQuery).not.toHaveBeenCalled()
    })

    it('reapplies the picked view once the list confirms it, when the query is the untouched default', async () => {
        persistSelection(SHARED_VIEW)
        const { logic, setQuery } = mountLogic(defaultSelect)

        await expectLogic(logic, () => {
            logic.actions.loadViews()
        }).toFinishAllListeners()

        expect(logic.values.currentView?.id).toEqual(SHARED_VIEW.id)
        expect(setQuery).toHaveBeenCalledTimes(1)
        expect(setQuery.mock.calls[0][0].select).toEqual(SHARED_VIEW.columns)
    })

    it('keeps the picked view but leaves a query the user already changed', async () => {
        persistSelection(SHARED_VIEW)
        const { logic, setQuery } = mountLogic([...defaultSelect, 'properties.email'])

        await expectLogic(logic, () => {
            logic.actions.loadViews()
        }).toFinishAllListeners()

        expect(logic.values.currentView?.id).toEqual(SHARED_VIEW.id)
        expect(setQuery).not.toHaveBeenCalled()
    })

    // The untouched default is the only query shape a view gets applied to, so a deleted view
    // paired with a changed query would pass whether or not the list is consulted first.
    it('clears a picked view the list no longer returns without touching the table', async () => {
        persistSelection({ ...SHARED_VIEW, id: 'fedcba98-7654-3210-fedc-ba9876543210', name: 'Deleted view' })
        const { logic, setQuery } = mountLogic(defaultSelect)

        await expectLogic(logic, () => {
            logic.actions.loadViews()
        }).toFinishAllListeners()

        expect(logic.values.currentView).toBeNull()
        expect(setQuery).not.toHaveBeenCalled()
    })
})
