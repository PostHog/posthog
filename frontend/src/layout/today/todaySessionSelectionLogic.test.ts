import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { todaySessionMenuLogic } from './todaySessionMenuLogic'
import { todaySessionSelectionLogic } from './todaySessionSelectionLogic'
import { todaySpacesLogic } from './todaySpacesLogic'

function task(id: string, lastActivityAt: string): Record<string, unknown> {
    return { id, title: id, archived: false, last_activity_at: lastActivityAt, channel: null, latest_run: null }
}

const PINNED = [task('pinned-1', '2026-09-20T10:00:00Z')]
const RECENT = [
    task('recent-1', '2026-09-28T10:00:00Z'),
    task('recent-2', '2026-09-27T10:00:00Z'),
    task('recent-3', '2026-09-26T10:00:00Z'),
]

describe('todaySessionSelectionLogic', () => {
    let logic: ReturnType<typeof todaySessionSelectionLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/tasks/': ({ request }) => {
                    const results = new URL(request.url).searchParams.get('pinned') ? PINNED : RECENT
                    return [200, { results, count: results.length }]
                },
                '/api/environments/:team_id/conversations/': { results: [], next: null },
            },
            post: {
                '/api/projects/:team_id/tasks/:id/pin/': ({ params }) =>
                    params.id === 'recent-2' ? [500, { detail: 'Server error' }] : [200, {}],
            },
        })
        initKeaTests()
        logic = todaySessionSelectionLogic()
        logic.mount()
        await expectLogic(todaySpacesLogic).toFinishAllListeners()
    })

    it.each([
        ['down the list', 'pinned-1', 'recent-2', ['pinned-1', 'recent-1', 'recent-2']],
        ['up the list', 'recent-1', 'pinned-1', ['recent-1', 'pinned-1']],
    ])('selects every session between the anchor and the Shift-clicked row %s', (_, anchor, target, expected) => {
        logic.actions.toggleSession(anchor)
        logic.actions.selectRange(target)

        expect(logic.values.visibleSelectedIds).toEqual(expected)
    })

    it('keeps only the failed sessions selected after a bulk action', async () => {
        logic.actions.setSelectedSessionIds(['recent-1', 'recent-2', 'recent-3'])
        todaySessionMenuLogic.actions.bulkSetSessionsPinned(logic.values.visibleSelectedIds, true)
        expect(logic.values.batchInProgress).toBe(true)

        await expectLogic(logic).toDispatchActions(['bulkSessionsSettled'])

        expect(logic.values.visibleSelectedIds).toEqual(['recent-2'])
        expect(logic.values.batchInProgress).toBe(false)
    })
})
