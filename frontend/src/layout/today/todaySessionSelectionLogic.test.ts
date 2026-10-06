import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { toast } from '@posthog/quill'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { todaySessionSelectionLogic } from './todaySessionSelectionLogic'
import { todaySpacesLogic } from './todaySpacesLogic'

const session = (id: string, lastActivityAt: string, run: Record<string, unknown> | null = null): object => ({
    id,
    title: id,
    archived: false,
    channel: null,
    last_activity_at: lastActivityAt,
    latest_run: run,
})

const PINNED = [session('task-p', '2026-09-28T12:00:00Z', { id: 'run-p', status: 'in_progress', environment: 'cloud' })]
const RECENT = [session('task-a', '2026-09-28T11:00:00Z'), session('task-b', '2026-09-28T10:00:00Z')]

const escapeHandledByMenu = (): void => {
    const event = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true })
    event.preventDefault()
    window.dispatchEvent(event)
}

const escapeFromOpenMenu = (): void => {
    const menu = document.createElement('div')
    menu.setAttribute('role', 'menu')
    menu.setAttribute('data-open', '')
    document.body.append(menu)
    menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    menu.remove()
}

describe('todaySessionSelectionLogic', () => {
    let logic: ReturnType<typeof todaySessionSelectionLogic.build>
    let requests: string[]
    let failingId: string | null

    const write = (label: string, id: string): [number, object] => {
        requests.push(`${label} ${id}`)
        return id === failingId ? [500, { detail: 'Server error' }] : [200, {}]
    }

    beforeEach(async () => {
        requests = []
        failingId = null
        jest.spyOn(toast, 'success')
        jest.spyOn(toast, 'error')
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/task_activity/': { results: [] },
                '/api/projects/:team_id/tasks/': ({ request }) => {
                    const pinned = new URL(request.url).searchParams.get('pinned')
                    return [200, { results: pinned ? PINNED : [...PINNED, ...RECENT], count: 3 }]
                },
            },
            patch: {
                '/api/projects/:team_id/tasks/:id/': async ({ params, request }) =>
                    write(`patch ${JSON.stringify(await request.json())}`, String(params.id)),
            },
            post: {
                '/api/projects/:team_id/tasks/:id/pin/': ({ params }) => write('pin', String(params.id)),
                '/api/projects/:team_id/tasks/:task_id/runs/:id/cancel/': ({ params }) =>
                    write(`cancel ${params.id}`, String(params.task_id)),
            },
        })
        initKeaTests()
        logic = todaySessionSelectionLogic()
        logic.mount()
        await expectLogic(todaySpacesLogic).toDispatchActions(['loadPinnedTasksSuccess', 'loadRecentTasksSuccess'])
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each([
        ['pin', () => logic.actions.pinSelected()],
        ['file', () => logic.actions.fileSelectedTo('space-1')],
        ['archive', () => logic.actions.requestBulkArchive()],
    ])('keeps only the failed sessions selected and shows one toast when a bulk %s partly fails', async (_, run) => {
        failingId = 'task-b'
        logic.actions.setSelection({ ids: ['task-a', 'task-b'], anchorId: 'task-b' })
        run()
        await expectLogic(logic).toDispatchActions(['bulkActionFinished'])

        expect(logic.values.selectedSessionIds).toEqual(['task-b'])
        expect(logic.values.bulkAction).toBeNull()
        expect(toast.error).toHaveBeenCalledTimes(1)
        expect(toast.success).not.toHaveBeenCalled()
    })

    it('asks before archiving a running session, then stops its run before archiving it', async () => {
        logic.actions.setSelection({ ids: ['task-p', 'task-a'], anchorId: 'task-a' })
        logic.actions.requestBulkArchive()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.bulkArchiveConfirm).toEqual({ open: true, count: 2, running: 1 })
        expect(requests).toEqual([])

        logic.actions.archiveSelected()
        await expectLogic(logic).toDispatchActions(['bulkActionFinished'])

        expect([...requests].sort()).toEqual([
            'cancel run-p task-p',
            'patch {"archived":true} task-a',
            'patch {"archived":true} task-p',
        ])
        expect(requests.indexOf('cancel run-p task-p')).toBeLessThan(requests.indexOf('patch {"archived":true} task-p'))
        expect(logic.values.selectedSessionIds).toEqual([])
        expect(logic.values.bulkArchiveConfirm.open).toBe(false)
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

    it.each([
        ['a menu already handled it', () => escapeHandledByMenu()],
        ['it comes from inside an open menu', () => escapeFromOpenMenu()],
    ])('keeps the selection on the first Escape when %s, and clears it on the next', (_, closeMenu) => {
        logic.actions.setSelection({ ids: ['task-a', 'task-b'], anchorId: 'task-b' })
        closeMenu()

        expect(logic.values.selectedSessionIds).toEqual(['task-a', 'task-b'])

        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))

        expect(logic.values.selectedSessionIds).toEqual([])
    })

    it.each([
        ['drops', 'a desktop window', 1280, []],
        ['keeps', 'a phone', 375, ['task-a']],
    ])('%s a picked session from a collapsed Recent section in %s', (_, __, width, expected) => {
        const originalWidth = window.innerWidth
        Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
        window.dispatchEvent(new Event('resize'))
        todaySpacesLogic.actions.toggleSection('recent')
        try {
            logic.actions.toggleSessionSelection('task-a')

            expect(logic.values.selectedSessionIds).toEqual(expected)
        } finally {
            todaySpacesLogic.actions.toggleSection('recent')
            Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth })
            window.dispatchEvent(new Event('resize'))
        }
    })
})
