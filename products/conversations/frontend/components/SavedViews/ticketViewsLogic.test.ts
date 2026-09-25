import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    type SupportTicketsSceneLogicProps,
    supportTicketsSceneLogic,
} from '../../scenes/tickets/supportTicketsSceneLogic'
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

const embeddedProps: SupportTicketsSceneLogicProps = { key: 'notebook-node-1', distinctIds: ['distinct-1'] }

describe('ticketViewsLogic', () => {
    let sceneLogic: ReturnType<typeof supportTicketsSceneLogic.build>
    let logic: ReturnType<typeof ticketViewsLogic.build>
    let createdFilters: Record<string, any> | undefined
    let updatedFilters: Record<string, any> | undefined

    beforeEach(() => {
        localStorage.clear()
        createdFilters = undefined
        updatedFilters = undefined
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/tickets/': () => [200, { count: 0, results: [] }],
                '/api/projects/:team_id/conversations/views/': () => [200, { results: [existingView] }],
            },
            post: {
                '/api/projects/:team_id/conversations/views/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    createdFilters = body.filters
                    return [
                        201,
                        {
                            id: 'view-new',
                            short_id: 'view-new',
                            name: 'Open tickets',
                            filters: body.filters,
                            created_at: '2026-01-02T00:00:00Z',
                            created_by: null,
                            is_favorited: false,
                        },
                    ]
                },
            },
            patch: {
                '/api/projects/:team_id/conversations/views/:short_id/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    updatedFilters = body.filters
                    return [200, { ...existingView, ...body }]
                },
            },
        })
        initKeaTests()
        router.actions.push(urls.supportTickets())
        sceneLogic = supportTicketsSceneLogic()
        sceneLogic.mount()
        logic = ticketViewsLogic({ ticketListProps: {} })
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

    it('saves and applies the filters of its own ticket list, not the default scene instance', async () => {
        const embeddedSceneLogic = supportTicketsSceneLogic(embeddedProps)
        embeddedSceneLogic.mount()
        const embeddedLogic = ticketViewsLogic({ ticketListProps: embeddedProps })
        embeddedLogic.mount()

        try {
            await expectLogic(sceneLogic, () => {
                sceneLogic.actions.setStatusFilter(['pending'])
            }).toFinishAllListeners()
            await expectLogic(embeddedSceneLogic, () => {
                embeddedSceneLogic.actions.setStatusFilter(['open'])
            }).toFinishAllListeners()

            embeddedLogic.actions.setViewName('Open tickets')
            await expectLogic(embeddedLogic, () => {
                embeddedLogic.actions.saveView()
            }).toFinishAllListeners()

            expect(createdFilters?.status).toEqual(['open'])
            expect(embeddedSceneLogic.values.activeView?.short_id).toBe('view-new')
            expect(sceneLogic.values.activeView).toBeNull()
            expect(sceneLogic.values.statusFilter).toEqual(['pending'])
        } finally {
            embeddedLogic.unmount()
            embeddedSceneLogic.unmount()
        }
    })

    it('keeps the detached view available to save after a filter change', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadView(existingView)
        }).toFinishAllListeners()
        expect(sceneLogic.values.activeView?.short_id).toBe('view-old')
        expect(sceneLogic.values.viewWithUnsavedChanges).toBeNull()

        await expectLogic(sceneLogic, () => {
            sceneLogic.actions.setPriorityFilter(['high'])
        }).toFinishAllListeners()
        expect(sceneLogic.values.activeView).toBeNull()
        expect(sceneLogic.values.viewWithUnsavedChanges?.short_id).toBe('view-old')

        await expectLogic(logic, () => {
            logic.actions.saveViewChanges()
        }).toFinishAllListeners()

        expect(updatedFilters?.priority).toEqual(['high'])
        expect(updatedFilters?.status).toEqual(['pending'])
        expect(sceneLogic.values.activeView?.short_id).toBe('view-old')
        expect(sceneLogic.values.viewWithUnsavedChanges).toBeNull()
    })

    it('discards an edit by restoring the filters the view was loaded with', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadView(existingView)
        }).toFinishAllListeners()

        await expectLogic(sceneLogic, () => {
            sceneLogic.actions.setPriorityFilter(['high'])
            sceneLogic.actions.setSearchQuery('refund')
        }).toFinishAllListeners()
        expect(sceneLogic.values.viewWithUnsavedChanges?.short_id).toBe('view-old')

        await expectLogic(sceneLogic, () => {
            sceneLogic.actions.restoreLoadedView()
        }).toFinishAllListeners()

        // The view pins only the status, so the rest has to come from the applied snapshot.
        expect(sceneLogic.values.priorityFilter).toEqual([])
        expect(sceneLogic.values.searchQuery).toBe('')
        expect(sceneLogic.values.statusFilter).toEqual(['pending'])
        expect(sceneLogic.values.activeView?.short_id).toBe('view-old')
        expect(sceneLogic.values.viewWithUnsavedChanges).toBeNull()
    })

    it('keeps an edit unsaved when the detached view is only renamed', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadView(existingView)
        }).toFinishAllListeners()

        await expectLogic(sceneLogic, () => {
            sceneLogic.actions.setPriorityFilter(['high'])
        }).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.updateView('view-old', { name: 'Renamed view' })
        }).toFinishAllListeners()

        expect(updatedFilters).toBeUndefined()
        expect(sceneLogic.values.activeView).toBeNull()
        expect(sceneLogic.values.viewWithUnsavedChanges?.short_id).toBe('view-old')
        expect(sceneLogic.values.priorityFilter).toEqual(['high'])
    })

    it('stops offering the detached view once the filters match it again', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadView(existingView)
        }).toFinishAllListeners()

        await expectLogic(sceneLogic, () => {
            sceneLogic.actions.setPriorityFilter(['high'])
        }).toFinishAllListeners()
        expect(sceneLogic.values.viewWithUnsavedChanges?.short_id).toBe('view-old')

        await expectLogic(sceneLogic, () => {
            sceneLogic.actions.setPriorityFilter([])
        }).toFinishAllListeners()
        expect(sceneLogic.values.viewWithUnsavedChanges).toBeNull()
    })
})
