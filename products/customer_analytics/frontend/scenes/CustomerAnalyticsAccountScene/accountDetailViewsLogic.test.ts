import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ColumnConfigurationApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { ACCOUNT_DETAIL_VIEWS_CONTEXT_KEY, BUILT_IN_VIEW_ID } from './accountDetailViews'
import { accountDetailViewsLogic } from './accountDetailViewsLogic'

const VIEWS_ENDPOINT = '/api/environments/:team_id/column_configurations/'

function buildRow(id: string, overrides: Partial<ColumnConfigurationApi> = {}): ColumnConfigurationApi {
    return {
        id,
        context_key: ACCOUNT_DETAIL_VIEWS_CONTEXT_KEY,
        name: `View ${id}`,
        columns: ['summary'],
        visibility: 'shared',
        properties: {},
        created_by: 1,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        ...overrides,
    }
}

describe('accountDetailViewsLogic', () => {
    let logic: ReturnType<typeof accountDetailViewsLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        userLogic.mount()
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, id: 1 })
    })

    afterEach(() => {
        logic?.unmount()
        userLogic.unmount()
    })

    it('shows the built-in view when nothing is saved, and hands its tab slot to the first saved view', async () => {
        const created = buildRow('created', { visibility: 'private', columns: ['summary', 'text'] })
        useMocks({
            get: { [VIEWS_ENDPOINT]: { count: 0, results: [] } },
            post: { [VIEWS_ENDPOINT]: created },
        })
        logic = accountDetailViewsLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadViewsSuccess'])
        expect(logic.values.pinnedViews.map((view) => view.id)).toEqual([BUILT_IN_VIEW_ID])

        logic.actions.addWidget(BUILT_IN_VIEW_ID, 'text')
        await expectLogic(logic).toDispatchActions(['createViewSuccess'])

        expect(logic.values.views.map((view) => view.id)).toEqual(['created'])
        expect(logic.values.pinnedViews.map((view) => view.id)).toEqual(['created'])
    })

    it('does not update a saved view owned by another user', async () => {
        const row = buildRow('shared', { created_by: 2 })
        useMocks({ get: { [VIEWS_ENDPOINT]: { count: 1, results: [row] } } })
        logic = accountDetailViewsLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadViewsSuccess'])

        logic.actions.addWidget(row.id, 'text')
        logic.actions.removeWidget(row.id, 'summary')
        logic.actions.setViewText(row.id, 'Changed')

        await expectLogic(logic).toNotHaveDispatchedActions(['updateView'])
        expect(logic.values.views[0]).toMatchObject({ widgets: ['summary'], text: '' })
    })

    it('caps pins at five and keeps a view from losing its last widget', async () => {
        const rows = ['a', 'b', 'c', 'd', 'e', 'f'].map((id) => buildRow(id))
        useMocks({ get: { [VIEWS_ENDPOINT]: { count: rows.length, results: rows } } })
        logic = accountDetailViewsLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadViewsSuccess'])
        expect(logic.values.pinnedViews.map((view) => view.id)).toEqual(['a', 'b', 'c', 'd', 'e'])
        expect(logic.values.canPinMore).toBe(false)

        logic.actions.pinView('f')
        expect(logic.values.pinnedViews.map((view) => view.id)).toEqual(['a', 'b', 'c', 'd', 'e'])

        logic.actions.unpinView('a')
        logic.actions.pinView('f')
        logic.actions.moveView('f', 'up')
        expect(logic.values.pinnedViews.map((view) => view.id)).toEqual(['b', 'c', 'd', 'f', 'e'])

        logic.actions.removeWidget('a', 'summary')
        await expectLogic(logic).toNotHaveDispatchedActions(['updateView'])
    })
})
