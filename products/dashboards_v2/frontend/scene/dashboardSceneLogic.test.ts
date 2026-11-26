import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import type { DashboardDocument } from '../dashboard/document/dashboardTypes'
import type { Board } from './boardApi'
import { dashboardSceneLogic } from './dashboardSceneLogic'

const BOARD_URL = '/api/projects/:team_id/dashboard_v2/boards/:uid/'

const spec = (title: string): DashboardDocument => ({
    version: 2,
    title,
    tabs: [
        {
            id: 'main',
            title: 'Main',
            tiles: [
                {
                    id: 'a',
                    place: { x: 0, y: 0, w: 6, h: 4 },
                    panel: { type: 'markdown', title: 'Notes', config: { text: 'Hi' } },
                },
            ],
        },
    ],
})

const board = (version: number, title: string): Board => ({
    uid: 'b1',
    version,
    managed_by: 'native',
    spec: spec(title),
})

type Save = { spec: DashboardDocument; base_version: number }

describe('dashboardSceneLogic', () => {
    let saves: Save[]
    let logic: ReturnType<typeof dashboardSceneLogic.build>

    const retitle = (title: string): void => {
        logic.actions.commitDashboard({ ...logic.values.dashboard!, title })
    }

    beforeEach(() => {
        saves = []
        initKeaTests()
    })

    afterEach(() => logic?.unmount())

    const useBoard = (respond: (save: Save) => [number, unknown]): void => {
        let stored: Board = {
            ...board(1, 'Mine'),
            spec: { ...spec('Mine'), user_access_level: AccessControlLevel.Viewer },
        }
        useMocks({
            get: { [BOARD_URL]: () => stored },
            put: {
                [BOARD_URL]: async ({ request }) => {
                    const save = (await request.json()) as Save
                    saves.push(save)
                    const [status, body] = respond(save)
                    if (status === 200) {
                        stored = body as Board
                    }
                    return [status, body]
                },
            },
        })
        logic = dashboardSceneLogic({ uid: 'b1' })
        logic.mount()
    }

    it('saves an edit made during a save against the version that save returned', async () => {
        useBoard((save) => [200, { ...board(save.base_version + 1, save.spec.title), spec: save.spec }])

        await expectLogic(logic).toFinishAllListeners()
        retitle('First')
        await expectLogic(logic).toDispatchActions(['saveStarted'])
        retitle('Second')
        await expectLogic(logic).toFinishAllListeners()

        expect(saves.map((save) => [save.base_version, save.spec.title])).toEqual([
            [1, 'First'],
            [2, 'Second'],
        ])
        expect(saves.some((save) => 'user_access_level' in save.spec)).toBe(false)
        expect(logic.values.saveState).toBe('saved')
    })

    it('stops saving on a conflict, shows both sides, and saves mine over theirs only when picked', async () => {
        let conflicted = false
        useBoard((save) => {
            if (!conflicted) {
                conflicted = true
                return [409, { detail: 'The board is at version 2' }]
            }
            return [200, { ...board(3, save.spec.title), spec: save.spec }]
        })
        await expectLogic(logic).toFinishAllListeners()
        useMocks({ get: { [BOARD_URL]: () => board(2, 'Theirs') } })

        retitle('Mine, edited')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.saveState).toBe('conflict')
        expect(logic.values.conflictChanges).toEqual({
            theirs: ['Renamed the dashboard to "Theirs"'],
            yours: ['Renamed the dashboard to "Mine, edited"'],
        })
        expect(logic.values.disabledReasonFor('moveTile')).not.toBeNull()

        logic.actions.keepMyVersion()
        await expectLogic(logic).toFinishAllListeners()

        expect(saves.map((save) => [save.base_version, save.spec.title])).toEqual([
            [1, 'Mine, edited'],
            [2, 'Mine, edited'],
        ])
        expect(logic.values.saveState).toBe('saved')
    })

    it('keeps their version without saving mine', async () => {
        useBoard(() => [409, {}])
        await expectLogic(logic).toFinishAllListeners()
        useMocks({ get: { [BOARD_URL]: () => board(2, 'Theirs') } })

        retitle('Mine, edited')
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.keepTheirVersion()
        await expectLogic(logic).toFinishAllListeners()

        expect(saves).toHaveLength(1)
        expect(logic.values.dashboard?.title).toBe('Theirs')
        expect(logic.values.saveState).toBe('saved')
        expect(logic.values.canUndo).toBe(false)
    })

    it('keeps an edit that failed to save, and saves it on retry', async () => {
        let fail = true
        useBoard((save) => (fail ? [500, {}] : [200, { ...board(2, save.spec.title), spec: save.spec }]))
        await expectLogic(logic).toFinishAllListeners()

        retitle('Mine, edited')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.saveState).toBe('failed')

        fail = false
        logic.actions.saveBoard()
        await expectLogic(logic).toFinishAllListeners()

        expect(saves.map((save) => [save.base_version, save.spec.title])).toEqual([
            [1, 'Mine, edited'],
            [1, 'Mine, edited'],
        ])
        expect(logic.values.saveState).toBe('saved')
    })

    it('makes a board managed outside PostHog read-only', async () => {
        useMocks({ get: { [BOARD_URL]: () => ({ ...board(1, 'Mine'), managed_by: 'iac' }) } })
        logic = dashboardSceneLogic({ uid: 'b1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.disabledReasonFor('moveTile')).toContain('managed outside PostHog')
    })

    it('saves a pending edit when the scene closes before the save delay ends', async () => {
        useBoard((save) => [200, { ...board(2, save.spec.title), spec: save.spec }])
        await expectLogic(logic).toFinishAllListeners()

        retitle('Mine, edited')
        logic.unmount()
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(saves.map((save) => save.spec.title)).toEqual(['Mine, edited'])
    })

    it('keeps the tab asked for in the URL while the board loads', async () => {
        router.actions.push('/dashboard-v2/b1', { tab: 'main' })
        useBoard(() => [200, {}])
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.searchParams.tab).toBe('main')
    })

    it.each([
        [404, 'notFound'],
        [403, 'noAccess'],
        [500, 'error'],
    ])('shows the %s load failure as %s', async (status, reason) => {
        useMocks({ get: { [BOARD_URL]: () => [status, {}] } })
        logic = dashboardSceneLogic({ uid: 'b1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.unavailable).toBe(reason)
        expect(logic.values.dashboard).toBeNull()
    })
})
