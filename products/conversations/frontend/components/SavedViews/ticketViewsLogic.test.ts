import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SavedTicketView, TicketViewFilters } from '../../types'
import { ticketViewsLogic } from './ticketViewsLogic'

function makeSavedView(shortId: string, filters: TicketViewFilters, isPrivate: boolean): SavedTicketView {
    return {
        id: shortId,
        short_id: shortId,
        name: `View ${shortId}`,
        filters,
        created_at: '2026-01-01T00:00:00Z',
        created_by: null,
        is_favorited: true,
        is_private: isPrivate,
    }
}

describe('ticketViewsLogic', () => {
    let logic: ReturnType<typeof ticketViewsLogic.build>
    let lastCreateBody: Record<string, any> | null = null

    beforeEach(() => {
        lastCreateBody = null
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/tickets/': () => [200, { count: 0, results: [] }],
                '/api/projects/:team_id/conversations/views/': () => [200, { count: 0, results: [] }],
            },
            post: {
                '/api/projects/:team_id/conversations/views/': async ({ request }) => {
                    lastCreateBody = (await request.json()) as Record<string, any>
                    return [
                        201,
                        {
                            ...lastCreateBody,
                            id: 'created',
                            short_id: 'created',
                            created_at: '2026-01-01T00:00:00Z',
                            created_by: null,
                            is_favorited: false,
                        },
                    ]
                },
            },
        })
        initKeaTests()
        logic = ticketViewsLogic({ id: 'test' })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it.each([
        ['a personal view', true],
        ['a shared view', false],
    ])(
        'duplicates %s as "Copy of ...", carrying filters and visibility but never the favorite',
        async (_label, isPrivate) => {
            await expectLogic(logic, () => {
                logic.actions.duplicateView(makeSavedView('abc', { status: ['open'] }, isPrivate))
            }).toDispatchActions(['createView', 'createViewSuccess'])

            expect(lastCreateBody?.name).toBe('Copy of View abc')
            expect(lastCreateBody?.filters).toEqual({ status: ['open'] })
            expect(lastCreateBody?.is_private).toBe(isPrivate)
            // Favorites are personal per user, so a duplicate must start un-favorited regardless of the source
            expect(lastCreateBody?.is_favorited).toBeUndefined()
        }
    )

    it('only blocks saving while a save is in flight, not while the list reloads', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadViews()
        }).toMatchValues({ viewsLoading: true, isSavingView: false })

        await expectLogic(logic).toFinishAllListeners()
    })

    it('saves a view as personal when the private toggle is set', async () => {
        logic.actions.setViewName('My personal view')
        logic.actions.setIsPrivate(true)

        await expectLogic(logic, () => {
            logic.actions.saveView()
        }).toDispatchActions(['createView', 'createViewSuccess'])

        expect(lastCreateBody?.name).toBe('My personal view')
        expect(lastCreateBody?.is_private).toBe(true)
    })
})
