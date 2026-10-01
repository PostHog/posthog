import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { todaySessionSelectionLogic } from './todaySessionSelectionLogic'
import { todaySpacesLogic } from './todaySpacesLogic'

const session = (id: string, lastActivityAt: string): object => ({
    id,
    title: id,
    archived: false,
    channel: null,
    last_activity_at: lastActivityAt,
    latest_run: null,
})

const PINNED = [session('task-p', '2026-09-28T12:00:00Z')]
const RECENT = [session('task-a', '2026-09-28T11:00:00Z'), session('task-b', '2026-09-28T10:00:00Z')]

describe('todaySessionSelectionLogic', () => {
    let logic: ReturnType<typeof todaySessionSelectionLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/task_activity/': { results: [] },
                '/api/projects/:team_id/tasks/': ({ request }) => {
                    const pinned = new URL(request.url).searchParams.get('pinned')
                    return [200, { results: pinned ? PINNED : [...PINNED, ...RECENT], count: 3 }]
                },
            },
        })
        initKeaTests()
        logic = todaySessionSelectionLogic()
        logic.mount()
        await expectLogic(todaySpacesLogic).toDispatchActions(['loadPinnedTasksSuccess', 'loadRecentTasksSuccess'])
    })

    it('starts a Shift-click range at the open session when nothing was clicked yet, across Pinned and Recent', async () => {
        router.actions.push(urls.aiTask('task-p'))
        logic.actions.selectSessionRange('task-b')

        expect(logic.values.selectedSessionIds).toEqual(['task-p', 'task-a', 'task-b'])
    })

    it.each([
        ['a route change', () => router.actions.push(urls.ai())],
        ['Escape', () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))],
    ])('clears the selection on %s', async (_, clear) => {
        logic.actions.setSelection({ ids: ['task-a', 'task-b'], anchorId: 'task-b' })
        clear()

        expect(logic.values.selectedSessionIds).toEqual([])
    })
})
