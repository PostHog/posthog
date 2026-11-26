import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { CURRENT_SCHEMA_VERSION, UnreadableBoardError, upgradeBoard } from '../dashboard/document/boardSchema'
import type { GridTab } from '../dashboard/document/dashboardTypes'
import { dashboardSceneLogic } from './dashboardSceneLogic'

// A board as a newer client could store it: a field this client doesn't know sits at every level.
const STORED_BOARD = {
    version: 2,
    title: 'Stored board',
    boardFromTheFuture: { kept: true },
    // Written by whoever saved the board, so it must never become the viewer's level.
    user_access_level: AccessControlLevel.Manager,
    panels: { shared: { type: 'markdown', config: { text: 'Shared' } } },
    tabs: [
        {
            id: 'overview',
            title: 'Overview',
            tabFromTheFuture: 1,
            tiles: [
                {
                    id: 'note',
                    place: { x: 0, y: 0, w: 12, h: 6 },
                    tileFromTheFuture: 'a',
                    panel: { type: 'markdown', config: { text: 'Hello' }, panelFromTheFuture: ['b'] },
                },
                { id: 'broken', place: { x: 0, y: 6, w: 12, h: 6 }, panel: null },
                {
                    id: 'section',
                    place: { x: 0, y: 12, w: 24, h: 3 },
                    panel: {
                        type: 'section',
                        title: 'More',
                        tiles: [{ id: 'inside', place: { x: 0, y: 0, w: 12, h: 6 }, panel: { ref: 'shared' } }],
                    },
                },
            ],
        },
    ],
}

describe('saved boards', () => {
    let savedBody: any
    let storedVersion: number

    beforeEach(() => {
        savedBody = null
        storedVersion = 3
        useMocks({
            get: {
                '/api/projects/:team/dashboard_v2/boards/stored/': () => [
                    200,
                    { uid: 'stored', version: storedVersion, spec: STORED_BOARD },
                ],
                '/api/projects/:team/dashboard_v2/boards/missing/': () => [404, { detail: 'Not found.' }],
            },
            post: {
                '/api/projects/:team/dashboard_v2/boards/': async ({ request }) => {
                    savedBody = await request.json()
                    return [201, { uid: 'copy', version: 1, spec: savedBody.spec }]
                },
            },
            put: {
                '/api/projects/:team/dashboard_v2/boards/stored/': async ({ request }) => {
                    savedBody = await request.json()
                    if (savedBody.base_version !== storedVersion) {
                        return [409, { detail: 'Conflict.' }]
                    }
                    storedVersion += 1
                    return [200, { uid: 'stored', version: storedVersion, spec: savedBody.spec }]
                },
            },
        })
        initKeaTests()
    })

    it('loads a stored board, keeps fields this client does not know through an edit, and saves it as a new board', async () => {
        const logic = dashboardSceneLogic()
        logic.mount()

        router.actions.push(urls.dashboardV2Board('stored'))
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.dashboard.title).toEqual('Stored board')
        expect(logic.values.dashboard.user_access_level).toBeUndefined()
        const tiles = (logic.values.dashboard.tabs[0] as GridTab).tiles
        expect(tiles.map((tile) => tile.id)).toEqual(['note', 'section'])
        expect(tiles[1].panel).toMatchObject({
            tiles: [{ id: 'inside', panel: { type: 'markdown', ref: 'shared', config: { text: 'Shared' } } }],
        })
        logic.actions.commitDashboard({ ...logic.values.dashboard, user_access_level: AccessControlLevel.Editor })

        logic.actions.applyDashboardEdit({ edit: 'addTab', title: 'Another' })
        logic.actions.saveAsBoard()
        await expectLogic(logic).toFinishAllListeners()

        const spec = savedBody.spec
        expect(spec.boardFromTheFuture).toEqual({ kept: true })
        expect(spec.tabs[0].tabFromTheFuture).toEqual(1)
        expect(spec.tabs[0].tiles[0].tileFromTheFuture).toEqual('a')
        expect(spec.tabs[0].tiles[0].panel.panelFromTheFuture).toEqual(['b'])
        expect(spec.panels).toEqual({ shared: { type: 'markdown', config: { text: 'Shared' } } })
        expect(spec.tabs).toHaveLength(2)
        expect(spec).not.toHaveProperty('user_access_level')
        expect(router.values.location.pathname).toContain(urls.dashboardV2Board('copy'))
    })

    it('saves a loaded board over the version it was loaded at, and refuses to save over a newer one', async () => {
        const logic = dashboardSceneLogic()
        logic.mount()
        router.actions.push(urls.dashboardV2Board('stored'))
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.saveBoard()
        await expectLogic(logic).toFinishAllListeners()
        expect(savedBody.base_version).toEqual(3)
        expect(logic.values.boardVersion).toEqual(4)

        storedVersion = 5
        logic.actions.saveBoard()
        await expectLogic(logic).toFinishAllListeners()
        expect(savedBody.base_version).toEqual(4)
        expect(logic.values.boardVersion).toEqual(4)
        expect(logic.values.savingBoard).toBe(false)
    })

    it('keeps a bookmarked tab of a saved board while the board loads', async () => {
        const logic = dashboardSceneLogic()
        logic.mount()

        router.actions.push(urls.dashboardV2Board('stored'), { tab: 'overview' })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.activeTab.id).toEqual('overview')
        expect(router.values.searchParams.tab).toEqual('overview')
    })

    it('stays on the fixture when going back to it before a board finishes loading', async () => {
        const logic = dashboardSceneLogic()
        logic.mount()

        router.actions.push(urls.dashboardV2Board('stored'))
        router.actions.push(urls.dashboardV2())
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.boardUid).toBeNull()
        expect(logic.values.dashboard.title).not.toEqual('Stored board')
    })

    it('shows the problem instead of the fixture when the board in the URL is missing', async () => {
        const logic = dashboardSceneLogic()
        logic.mount()

        router.actions.push(urls.dashboardV2Board('missing'))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.boardError).toEqual({ problem: 'notFound' })
    })

    it.each([
        ['a newer schema than this client reads', { ...STORED_BOARD, version: CURRENT_SCHEMA_VERSION + 1 }],
        ['a classic dashboard', { ...STORED_BOARD, version: 1 }],
        ['no tab with tiles', { ...STORED_BOARD, tabs: [{ id: 'docs', title: 'Docs', href: '/docs' }] }],
        ['not an object', [STORED_BOARD]],
        ['a title that is not text', { ...STORED_BOARD, title: { text: 'Stored board' } }],
        ['a tab whose title is not text', { ...STORED_BOARD, tabs: [{ ...STORED_BOARD.tabs[0], title: 1 }] }],
    ])('refuses to load %s', (_name, stored) => {
        expect(() => upgradeBoard(stored)).toThrow(UnreadableBoardError)
    })
})
