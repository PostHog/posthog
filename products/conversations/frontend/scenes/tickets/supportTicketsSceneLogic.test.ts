import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

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
})
