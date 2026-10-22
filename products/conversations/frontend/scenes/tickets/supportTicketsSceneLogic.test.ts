import { MOCK_DEFAULT_ORGANIZATION_MEMBER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { membersLogic } from 'scenes/organization/membersLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { MAX_ASSIGNEE_FILTER_ENTRIES, assigneeSelectLogic } from '../../components/Assignee'
import { normalizeAssigneeFilter, type SavedTicketView, type Ticket, type TicketViewFilters } from '../../types'
import { supportTicketsSceneLogic } from './supportTicketsSceneLogic'

function makeTicket(id: string, userAccessLevel?: AccessControlLevel): Ticket {
    return {
        id,
        ticket_number: 1,
        distinct_id: `distinct-${id}`,
        status: 'open',
        channel_source: 'email',
        anonymous_traits: {},
        identity_verified: false,
        ai_resolved: false,
        created_at: '2026-06-12T00:00:00Z',
        updated_at: '2026-06-12T00:00:00Z',
        message_count: 1,
        last_message_at: '2026-06-12T00:00:00Z',
        last_message_text: 'Hello',
        unread_team_count: 0,
        unread_customer_count: 0,
        user_access_level: userAccessLevel,
    }
}

function makeSavedView(shortId: string, filters: TicketViewFilters = {}): SavedTicketView {
    return {
        id: shortId,
        short_id: shortId,
        name: `View ${shortId}`,
        filters,
        created_at: '2026-01-01T00:00:00Z',
        created_by: null,
        is_favorited: false,
    }
}

async function waitUntilPending(pending: Record<string, unknown>, shortId: string): Promise<void> {
    for (let i = 0; i < 20 && !pending[shortId]; i++) {
        await Promise.resolve()
    }
}

describe('supportTicketsSceneLogic', () => {
    beforeEach(() => {
        localStorage.clear()
    })

    describe('editable selected ticket IDs', () => {
        let logic: ReturnType<typeof supportTicketsSceneLogic.build>

        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/:team_id/conversations/tickets/': () => [200, { results: [], count: 0 }],
                },
            })
            initKeaTests()
            logic = supportTicketsSceneLogic()
            logic.mount()
        })

        afterEach(() => {
            logic.unmount()
        })

        // Regression: bulk status updates must only ever be sent for tickets the caller can edit.
        // The backend already enforces this (silently skipping non-editable IDs), but a selection
        // mixing editable and view-only tickets should be filtered client-side too, not just relayed
        // wholesale to the API.
        it('filters out tickets the user cannot edit at the object level', () => {
            const editable = makeTicket('editable', AccessControlLevel.Editor)
            const viewerOnly = makeTicket('viewer-only', AccessControlLevel.Viewer)
            const noAccess = makeTicket('no-access', AccessControlLevel.None)
            const unset = makeTicket('unset')

            expectLogic(logic, () => {
                logic.actions.setTickets([editable, viewerOnly, noAccess, unset])
                logic.actions.setSelectedTicketIds([editable.id, viewerOnly.id, noAccess.id, unset.id])
            }).toMatchValues({
                editableSelectedTicketIds: [editable.id, unset.id],
            })
        })

        it('includes every selected ticket when none are access-restricted', () => {
            const a = makeTicket('a', AccessControlLevel.Editor)
            const b = makeTicket('b', AccessControlLevel.Manager)

            expectLogic(logic, () => {
                logic.actions.setTickets([a, b])
                logic.actions.setSelectedTicketIds([a.id, b.id])
            }).toMatchValues({
                editableSelectedTicketIds: [a.id, b.id],
            })
        })
    })

    describe('normalizeAssigneeFilter', () => {
        it.each([
            ['legacy "all"', 'all', []],
            ['legacy "unassigned"', 'unassigned', ['unassigned']],
            ['dynamic "me"', 'me', ['me']],
            ['legacy single user', { type: 'user', id: 1 }, [{ type: 'user', id: 1 }]],
            ['undefined', undefined, []],
            ['null', null, []],
            ['a stray number', 42, []],
            [
                'an array with invalid entries',
                ['unassigned', { type: 'user', id: 1 }, { type: 'nope', id: 2 }, 'all'],
                ['unassigned', { type: 'user', id: 1 }],
            ],
        ])('normalizes %s', (_label, input, expected) => {
            expect(normalizeAssigneeFilter(input)).toEqual(expected)
        })

        it('caps oversized arrays at the API entry limit', () => {
            const oversized = Array.from({ length: MAX_ASSIGNEE_FILTER_ENTRIES + 50 }, (_, i) => ({
                type: 'user' as const,
                id: i,
            }))
            expect(normalizeAssigneeFilter(oversized)).toHaveLength(MAX_ASSIGNEE_FILTER_ENTRIES)
        })
    })

    describe('assignee filter param', () => {
        let logic: ReturnType<typeof supportTicketsSceneLogic.build>
        let lastAssigneeParam: string | null = null

        beforeEach(() => {
            lastAssigneeParam = null
            useMocks({
                get: {
                    '/api/projects/:team_id/conversations/tickets/': ({ request }) => {
                        lastAssigneeParam = new URL(request.url).searchParams.get('assignee')
                        return [200, { count: 0, results: [] }]
                    },
                },
            })
            initKeaTests()
            logic = supportTicketsSceneLogic()
            logic.mount()
        })

        afterEach(() => {
            logic?.unmount()
        })

        it('joins selected entries into a comma-separated param and normalizes legacy view filters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setAssigneeFilter(['unassigned', { type: 'user', id: 1 }, { type: 'role', id: 'abc' }])
            }).toFinishAllListeners()
            expect(lastAssigneeParam).toBe('unassigned,user:1,role:abc')

            await expectLogic(logic, () => {
                logic.actions.applyViewFilters({ assignee: 'unassigned' })
            }).toFinishAllListeners()
            expect(logic.values.assigneeFilterEntries).toEqual(['unassigned'])
            expect(lastAssigneeParam).toBe('unassigned')
        })

        it('passes the dynamic "me" token through unchanged so the backend resolves the viewer', async () => {
            await expectLogic(logic, () => {
                logic.actions.setAssigneeFilter(['me', { type: 'user', id: 1 }])
            }).toFinishAllListeners()
            expect(lastAssigneeParam).toBe('me,user:1')

            // A saved view scoped to "me" round-trips as the portable token, not a
            // concrete user id — so it stays each viewer's own tickets.
            await expectLogic(logic, () => {
                logic.actions.applyViewFilters({ assignee: ['me'] })
            }).toFinishAllListeners()
            expect(logic.values.assigneeFilterEntries).toEqual(['me'])
            expect(lastAssigneeParam).toBe('me')
        })
    })

    describe('URL sync', () => {
        let logic: ReturnType<typeof supportTicketsSceneLogic.build>

        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/:team_id/conversations/tickets/': () => [200, { count: 0, results: [] }],
                    '/api/projects/:team_id/conversations/views/:short_id/': () => [404, { detail: 'Not found' }],
                },
            })
            initKeaTests()
        })

        afterEach(() => {
            logic?.unmount()
        })

        it('writes active filters to the URL so links are shareable', async () => {
            router.actions.push(urls.supportTickets())
            logic = supportTicketsSceneLogic()
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setStatusFilter(['open', 'new'])
                logic.actions.setChannelFilter('slack')
                logic.actions.setAssigneeFilter([{ type: 'user', id: 1 }])
                logic.actions.setSorting({ columnKey: 'created_at', order: 1 })
                logic.actions.setSearchQuery('customer@example.com')
            }).toFinishAllListeners()

            expect(router.values.searchParams.status).toEqual(['open', 'new'])
            expect(router.values.searchParams.channel).toBe('slack')
            expect(router.values.searchParams.assignee).toEqual(['user:1'])
            expect(router.values.searchParams.order_by).toBe('created_at')
            expect(router.values.searchParams.search).toBeUndefined()
        })

        it('applies shareable filters from the URL but removes free-text search', async () => {
            router.actions.push(urls.supportTickets(), {
                status: ['pending'],
                channel: 'email',
                order_by: 'created_at',
                assignee: ['unassigned'],
                search: 'customer@example.com',
            })
            logic = supportTicketsSceneLogic()
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.statusFilter).toEqual(['pending'])
            expect(logic.values.channelFilter).toBe('email')
            expect(logic.values.sorting).toEqual({ columnKey: 'created_at', order: 1 })
            expect(logic.values.assigneeFilterEntries).toEqual(['unassigned'])
            expect(logic.values.searchQuery).toBe('')
            expect(router.values.searchParams.search).toBeUndefined()
        })

        it('detaches an active view when the URL changes to explicit filters', async () => {
            router.actions.push(urls.supportTickets())
            logic = supportTicketsSceneLogic()
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.applyView(makeSavedView('view-a', { status: ['open'], dateFrom: '-24h' }))
            }).toFinishAllListeners()

            router.actions.push(urls.supportTickets(), { status: ['pending'] })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.activeView).toBeNull()
            expect(logic.values.statusFilter).toEqual(['pending'])
            expect(logic.values.dateFrom).toBe('-7d')
            expect(router.values.searchParams).toMatchObject({ status: ['pending'] })
            expect(router.values.searchParams.view).toBeUndefined()
        })

        it('ignores a saved view response after navigating to explicit filters', async () => {
            const pending: Record<string, { resolve: (view: SavedTicketView) => void }> = {}
            useMocks({
                get: {
                    '/api/projects/:team_id/conversations/views/:short_id/': ({ request }) => {
                        const pathParts = new URL(request.url).pathname.split('/')
                        const shortId = pathParts[pathParts.length - 2]
                        return new Promise((resolve) => {
                            pending[shortId] = { resolve: (view) => resolve([200, view]) }
                        })
                    },
                },
            })
            router.actions.push(urls.supportTickets(), { view: 'view-a' })
            logic = supportTicketsSceneLogic()
            logic.mount()
            await waitUntilPending(pending, 'view-a')

            router.actions.push(urls.supportTickets(), { status: ['pending'] })
            pending['view-a'].resolve(makeSavedView('view-a', { status: ['open'] }))
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.activeView).toBeNull()
            expect(logic.values.statusFilter).toEqual(['pending'])
            expect(router.values.searchParams).toMatchObject({ status: ['pending'] })
            expect(router.values.searchParams.view).toBeUndefined()
        })

        it('keeps a new sort order applied when sorting while a saved view is active', async () => {
            let lastOrderBy: string | null = null
            useMocks({
                get: {
                    '/api/projects/:team_id/conversations/tickets/': ({ request }) => {
                        lastOrderBy = new URL(request.url).searchParams.get('order_by')
                        return [200, { count: 0, results: [] }]
                    },
                    '/api/projects/:team_id/conversations/views/:short_id/': () => [
                        200,
                        makeSavedView('view-a', { status: ['open'] }),
                    ],
                },
            })
            router.actions.push(urls.supportTickets(), { view: 'view-a' })
            logic = supportTicketsSceneLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.activeView?.short_id).toBe('view-a')

            await expectLogic(logic, () => {
                logic.actions.setSorting({ columnKey: 'sla_due_at', order: -1 })
            }).toFinishAllListeners()

            // Sorting detaches the view but the sort and the view's filters must stick, and the
            // new order has to reach the API instead of snapping back to the default sort.
            expect(logic.values.activeView).toBeNull()
            expect(logic.values.sorting).toEqual({ columnKey: 'sla_due_at', order: -1 })
            expect(logic.values.statusFilter).toEqual(['open'])
            expect(lastOrderBy).toBe('-sla_due_at')
        })

        const persistedViewMocks = {
            get: {
                '/api/projects/:team_id/conversations/tickets/': () => [200, { count: 0, results: [] }],
                '/api/projects/:team_id/conversations/views/:short_id/': () => [
                    200,
                    makeSavedView('view-a', { status: ['open'], dateFrom: '-24h' }),
                ],
            },
        }

        async function reopenTickets(
            searchParams: Record<string, any> = {}
        ): Promise<ReturnType<typeof supportTicketsSceneLogic.build>> {
            router.actions.push(urls.supportTickets())
            const first = supportTicketsSceneLogic()
            first.mount()
            await expectLogic(first, () => {
                first.actions.applyView(makeSavedView('view-a', { status: ['open'], dateFrom: '-24h' }))
            }).toFinishAllListeners()
            first.unmount()

            // A new kea context reads the persisted view the way a reopened page does.
            initKeaTests()
            router.actions.push(urls.supportTickets(), searchParams)
            const reopened = supportTicketsSceneLogic()
            reopened.mount()
            await expectLogic(reopened).toFinishAllListeners()
            return reopened
        }

        it('reapplies a persisted saved view when the ticket list opens without a view param', async () => {
            useMocks(persistedViewMocks)
            logic = await reopenTickets()

            expect(logic.values.activeView?.short_id).toBe('view-a')
            expect(logic.values.statusFilter).toEqual(['open'])
            expect(logic.values.dateFrom).toBe('-24h')
            expect(router.values.searchParams.view).toBe('view-a')
        })

        it('keeps the list loading while a persisted view is still reloading', async () => {
            const pending: Record<string, { resolve: (view: SavedTicketView) => void }> = {}
            useMocks({
                get: {
                    '/api/projects/:team_id/conversations/tickets/': () => [200, { count: 0, results: [] }],
                    '/api/projects/:team_id/conversations/views/:short_id/': () =>
                        new Promise((resolve) => {
                            pending['view-a'] = { resolve: (view) => resolve([200, view]) }
                        }),
                },
            })
            router.actions.push(urls.supportTickets())
            const first = supportTicketsSceneLogic()
            first.mount()
            await expectLogic(first, () => {
                first.actions.applyView(makeSavedView('view-a', { status: ['open'] }))
            }).toFinishAllListeners()
            first.unmount()

            initKeaTests()
            router.actions.push(urls.supportTickets())
            logic = supportTicketsSceneLogic()
            logic.mount()

            expect(logic.values.ticketsLoading).toBe(true)
            expect(logic.values.tickets).toEqual([])

            await waitUntilPending(pending, 'view-a')
            pending['view-a'].resolve(makeSavedView('view-a', { status: ['open'] }))
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.ticketsLoading).toBe(false)
            expect(logic.values.activeView?.short_id).toBe('view-a')
        })

        it('ignores a restore response after another saved view is selected', async () => {
            const pending: Record<string, { resolve: (view: SavedTicketView) => void }> = {}
            useMocks({
                get: {
                    '/api/projects/:team_id/conversations/tickets/': () => [200, { count: 0, results: [] }],
                    '/api/projects/:team_id/conversations/views/:short_id/': () =>
                        new Promise((resolve) => {
                            pending['view-a'] = { resolve: (view) => resolve([200, view]) }
                        }),
                },
            })
            router.actions.push(urls.supportTickets())
            const first = supportTicketsSceneLogic()
            first.mount()
            await expectLogic(first, () => {
                first.actions.applyView(makeSavedView('view-a', { status: ['open'] }))
            }).toFinishAllListeners()
            first.unmount()

            initKeaTests()
            router.actions.push(urls.supportTickets())
            logic = supportTicketsSceneLogic()
            logic.mount()
            await waitUntilPending(pending, 'view-a')

            logic.actions.applyView(makeSavedView('view-b', { status: ['pending'] }))
            pending['view-a'].resolve(makeSavedView('view-a', { status: ['open'] }))
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.activeView?.short_id).toBe('view-b')
            expect(logic.values.statusFilter).toEqual(['pending'])
            expect(router.values.searchParams.view).toBe('view-b')
        })

        it('drops an in-flight view link when the list opens with nothing persisted', async () => {
            const pending: Record<string, { resolve: (view: SavedTicketView) => void }> = {}
            useMocks({
                get: {
                    '/api/projects/:team_id/conversations/tickets/': () => [200, { count: 0, results: [] }],
                    '/api/projects/:team_id/conversations/views/:short_id/': () =>
                        new Promise((resolve) => {
                            pending['view-a'] = { resolve: (view) => resolve([200, view]) }
                        }),
                },
            })
            router.actions.push(urls.supportTickets(), { view: 'view-a' })
            logic = supportTicketsSceneLogic()
            logic.mount()
            await waitUntilPending(pending, 'view-a')

            router.actions.push(urls.supportTickets())
            pending['view-a'].resolve(makeSavedView('view-a', { status: ['open'] }))
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.activeView).toBeNull()
            expect(logic.values.statusFilter).toEqual([])
            expect(router.values.searchParams.view).toBeUndefined()
        })

        it('lets an explicit filter link override a persisted saved view', async () => {
            useMocks(persistedViewMocks)
            logic = await reopenTickets({ status: ['pending'] })

            expect(logic.values.activeView).toBeNull()
            expect(logic.values.statusFilter).toEqual(['pending'])
            expect(logic.values.dateFrom).toBe('-7d')
            expect(router.values.searchParams.view).toBeUndefined()
        })

        it('resets stale view filters when a linked view is missing', async () => {
            router.actions.push(urls.supportTickets())
            logic = supportTicketsSceneLogic()
            logic.mount()
            await expectLogic(logic, () => {
                logic.actions.applyView(makeSavedView('view-a', { status: ['open'], dateFrom: '-24h' }))
            }).toFinishAllListeners()

            router.actions.push(urls.supportTickets(), { view: 'deadbeef' })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.activeView).toBeNull()
            expect(logic.values.statusFilter).toEqual([])
            expect(logic.values.dateFrom).toBe('-7d')
            expect(router.values.searchParams.view).toBeUndefined()
        })
    })

    describe('assignee names', () => {
        let logic: ReturnType<typeof supportTicketsSceneLogic.build>

        afterEach(() => {
            logic?.unmount()
        })

        it('loads organization members on mount so a user assignee resolves to a name', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/conversations/tickets/': () => [200, { count: 0, results: [] }],
                },
            })
            initKeaTests()
            router.actions.push(urls.supportTickets())
            logic = supportTicketsSceneLogic()
            logic.mount()

            await expectLogic(membersLogic).toDispatchActions(['loadAllMembersSuccess'])

            expect(
                assigneeSelectLogic.values.resolveAssignee({
                    type: 'user',
                    id: MOCK_DEFAULT_ORGANIZATION_MEMBER.user.id,
                })
            ).toMatchObject({ type: 'user', id: MOCK_DEFAULT_ORGANIZATION_MEMBER.user.id })
        })
    })

    describe('breadcrumbs', () => {
        let logic: ReturnType<typeof supportTicketsSceneLogic.build>

        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/:team_id/conversations/tickets/': () => [200, { count: 0, results: [] }],
                },
            })
            initKeaTests()
            router.actions.push(urls.supportTickets())
            logic = supportTicketsSceneLogic()
            logic.mount()
        })

        afterEach(() => {
            logic?.unmount()
        })

        it('falls back to the generic scene name with no saved view applied', () => {
            expect(logic.values.breadcrumbs).toEqual([{ key: Scene.SupportTickets, name: 'Ticket list' }])
        })

        it("uses the saved view's name while a view is applied, and drops it on detach", async () => {
            await expectLogic(logic, () => {
                logic.actions.applyView(makeSavedView('view-a'))
            }).toFinishAllListeners()

            expect(logic.values.breadcrumbs).toEqual([{ key: Scene.SupportTickets, name: 'View view-a' }])

            await expectLogic(logic, () => {
                logic.actions.clearActiveView()
            }).toFinishAllListeners()

            expect(logic.values.breadcrumbs).toEqual([{ key: Scene.SupportTickets, name: 'Ticket list' }])
        })
    })
})
