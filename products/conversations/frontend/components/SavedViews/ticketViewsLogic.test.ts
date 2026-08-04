import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SavedTicketView } from '../../types'
import { ticketViewsLogic } from './ticketViewsLogic'

function makeSavedView(shortId: string, overrides: Partial<SavedTicketView> = {}): SavedTicketView {
    return {
        id: shortId,
        short_id: shortId,
        name: `View ${shortId}`,
        filters: {},
        created_at: '2026-01-01T00:00:00Z',
        created_by: null,
        is_favorited: false,
        is_default: false,
        ...overrides,
    }
}

describe('ticketViewsLogic', () => {
    let logic: ReturnType<typeof ticketViewsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/tickets/': () => [200, { count: 0, results: [] }],
                '/api/projects/:team_id/conversations/views/default/': () => [200, { default_view: null }],
                '/api/projects/:team_id/conversations/views/': () => [200, { count: 0, results: [] }],
            },
        })
        initKeaTests()
        logic = ticketViewsLogic({ id: 'test' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    // Only one view can be the default, and the server enforces that with a single-row upsert —
    // it never tells us which view lost the flag, so the list has to demote the old one itself.
    it('demotes the previous default when another view is promoted', async () => {
        const first = makeSavedView('first', { is_default: true })
        const second = makeSavedView('second')

        await expectLogic(logic, () => {
            logic.actions.loadViewsSuccess([first, second])
            logic.actions.viewUpdated({ ...second, is_default: true })
        }).toFinishAllListeners()

        expect(logic.values.views.map((v) => [v.short_id, v.is_default])).toEqual([
            ['first', false],
            ['second', true],
        ])
    })

    it('heads the dropdown with the default view even when it is not a favorite', async () => {
        const favorite = makeSavedView('favorite', { is_favorited: true })
        const theDefault = makeSavedView('default', { is_default: true })

        await expectLogic(logic, () => {
            logic.actions.loadViewsSuccess([favorite, theDefault])
        }).toFinishAllListeners()

        expect(logic.values.dropdownViews.map((v) => v.short_id)).toEqual(['default', 'favorite'])
    })
})
