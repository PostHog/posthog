import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { MAX_ASSIGNEE_FILTER_ENTRIES } from '../../components/Assignee'
import { normalizeAssigneeFilter } from '../../types'
import { supportTicketsSceneLogic } from './supportTicketsSceneLogic'

describe('supportTicketsSceneLogic', () => {
    describe('normalizeAssigneeFilter', () => {
        it.each([
            ['legacy "all"', 'all', []],
            ['legacy "unassigned"', 'unassigned', ['unassigned']],
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
    })

    describe('URL sync', () => {
        let logic: ReturnType<typeof supportTicketsSceneLogic.build>

        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/:team_id/conversations/tickets/': () => [200, { count: 0, results: [] }],
                    '/api/environments/:team_id/conversations/views/:short_id': () => [404, { detail: 'Not found' }],
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
            }).toFinishAllListeners()

            expect(router.values.searchParams.status).toEqual(['open', 'new'])
            expect(router.values.searchParams.channel).toBe('slack')
            expect(router.values.searchParams.assignee).toEqual(['user:1'])
            expect(router.values.searchParams.order_by).toBe('created_at')
        })

        it('applies filters from the URL on mount so bookmarked links restore them', async () => {
            router.actions.push(urls.supportTickets(), {
                status: ['pending'],
                channel: 'email',
                order_by: 'created_at',
                assignee: ['unassigned'],
            })
            logic = supportTicketsSceneLogic()
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.statusFilter).toEqual(['pending'])
            expect(logic.values.channelFilter).toBe('email')
            expect(logic.values.sorting).toEqual({ columnKey: 'created_at', order: 1 })
            expect(logic.values.assigneeFilterEntries).toEqual(['unassigned'])
        })

        it('drops the view param and falls back to loading tickets when a linked view is missing', async () => {
            router.actions.push(urls.supportTickets(), { view: 'deadbeef' })
            logic = supportTicketsSceneLogic()
            logic.mount()

            await expectLogic(logic)
                .toDispatchActions(['loadSavedView', 'clearActiveView', 'loadTickets'])
                .toFinishAllListeners()

            expect(logic.values.activeView).toBeNull()
            expect(router.values.searchParams.view).toBeUndefined()
        })
    })
})
