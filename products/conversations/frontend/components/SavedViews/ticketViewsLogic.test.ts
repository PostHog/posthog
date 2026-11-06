import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { supportTicketsSceneLogic } from '../../scenes/tickets/supportTicketsSceneLogic'
import type { SavedTicketView } from '../../types'
import { ticketViewsLogic } from './ticketViewsLogic'

const existingView: SavedTicketView = {
    id: 'view-old',
    short_id: 'view-old',
    name: 'Old view',
    filters: { status: ['pending'] },
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    is_favorited: false,
}

describe('ticketViewsLogic', () => {
    let sceneLogic: ReturnType<typeof supportTicketsSceneLogic.build>
    let logic: ReturnType<typeof ticketViewsLogic.build>

    beforeEach(() => {
        localStorage.clear()
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/tickets/': () => [200, { count: 0, results: [] }],
                '/api/projects/:team_id/conversations/views/': () => [200, { results: [existingView] }],
            },
            post: {
                '/api/projects/:team_id/conversations/views/': () => [
                    201,
                    {
                        id: 'view-new',
                        short_id: 'view-new',
                        name: 'Open tickets',
                        filters: { status: ['open'] },
                        created_at: '2026-01-02T00:00:00Z',
                        created_by: null,
                        is_favorited: false,
                    },
                ],
            },
        })
        initKeaTests()
        router.actions.push(urls.supportTickets())
        sceneLogic = supportTicketsSceneLogic()
        sceneLogic.mount()
        logic = ticketViewsLogic({ id: 'SupportTicketsScene' })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        sceneLogic?.unmount()
    })

    it('selects the view just saved so it shows as the active saved view', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadViews()
        }).toFinishAllListeners()
        expect(logic.values.views.map((view) => view.short_id)).toEqual(['view-old'])

        await expectLogic(sceneLogic, () => {
            sceneLogic.actions.setStatusFilter(['open'])
        }).toFinishAllListeners()

        logic.actions.setViewName('Open tickets')
        await expectLogic(logic, () => {
            logic.actions.saveView()
        }).toFinishAllListeners()

        expect(sceneLogic.values.activeView?.short_id).toBe('view-new')
        expect(sceneLogic.values.activeView?.name).toBe('Open tickets')
        expect(sceneLogic.values.statusFilter).toEqual(['open'])
        expect(router.values.searchParams.view).toBe('view-new')
    })
})
