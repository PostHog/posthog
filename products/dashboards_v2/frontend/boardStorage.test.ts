import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { CURRENT_SCHEMA_VERSION, UnreadableBoardError, boardDocument, upgradeBoard } from './dashboard/boardSchema'
import { loadDashboard } from './dashboard/sharedPanels'
import { dashboardV2Logic } from './dashboardV2Logic'

// A board as a newer client could store it: a field this client doesn't know sits at every level.
const STORED_BOARD = {
    version: 2,
    title: 'Stored board',
    boardFromTheFuture: { kept: true },
    // Written by whoever saved the board, so it must never become the viewer's level.
    user_access_level: AccessControlLevel.Manager,
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
            ],
        },
    ],
}

describe('saved boards', () => {
    let savedSpec: any

    beforeEach(() => {
        savedSpec = null
        useMocks({
            get: {
                '/api/projects/:team/dashboard_v2/boards/stored/': { uid: 'stored', version: 1, spec: STORED_BOARD },
                '/api/projects/:team/dashboard_v2/boards/missing/': () => [404, { detail: 'Not found.' }],
            },
            post: {
                '/api/projects/:team/dashboard_v2/boards/': async ({ request }) => {
                    savedSpec = ((await request.json()) as { spec: unknown }).spec
                    return [201, { uid: 'copy', version: 1, spec: savedSpec }]
                },
            },
        })
        initKeaTests()
    })

    it('loads a stored board, keeps fields this client does not know through an edit, and saves them back', async () => {
        const logic = dashboardV2Logic()
        logic.mount()

        router.actions.push(urls.dashboardV2Board('stored'))
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.dashboard.title).toEqual('Stored board')
        expect(logic.values.dashboard.user_access_level).toBeUndefined()
        expect((logic.values.dashboard.tabs[0] as { tiles: unknown[] }).tiles.map((tile: any) => tile.id)).toEqual([
            'note',
        ])
        // The viewer's level comes from access control, never from the stored board.
        logic.actions.commitDashboard({ ...logic.values.dashboard, user_access_level: AccessControlLevel.Editor })

        logic.actions.applyDashboardEdit({ edit: 'addTab', title: 'Another' })
        logic.actions.saveAsBoard()
        await expectLogic(logic).toFinishAllListeners()

        expect(savedSpec.boardFromTheFuture).toEqual({ kept: true })
        expect(savedSpec.tabs[0].tabFromTheFuture).toEqual(1)
        expect(savedSpec.tabs[0].tiles[0].tileFromTheFuture).toEqual('a')
        expect(savedSpec.tabs[0].tiles[0].panel.panelFromTheFuture).toEqual(['b'])
        expect(savedSpec.tabs).toHaveLength(2)
        expect(savedSpec).not.toHaveProperty('user_access_level')
        expect(router.values.location.pathname).toContain(urls.dashboardV2Board('copy'))
    })

    it('loads a version 2 document that names its panels widgets, and saves it with panels', () => {
        const legacy = {
            version: 2,
            title: 'Written before the rename',
            widgets: { shared: { type: 'markdown', config: { text: 'Shared' } } },
            tabs: [
                {
                    id: 'main',
                    title: 'Main',
                    tiles: [
                        { id: 'a', place: { x: 0, y: 0, w: 12, h: 6 }, widget: { ref: 'shared' } },
                        {
                            id: 's',
                            place: { x: 0, y: 6, w: 24, h: 3 },
                            widget: {
                                type: 'section',
                                title: 'More',
                                tiles: [
                                    {
                                        id: 'b',
                                        place: { x: 0, y: 0, w: 12, h: 6 },
                                        widget: { type: 'markdown', config: { text: 'Inside' } },
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        }

        const saved = boardDocument(loadDashboard(upgradeBoard(legacy)))

        expect(saved).toEqual({
            version: 2,
            title: 'Written before the rename',
            panels: { shared: { type: 'markdown', config: { text: 'Shared' } } },
            tabs: [
                {
                    id: 'main',
                    title: 'Main',
                    tiles: [
                        { id: 'a', place: { x: 0, y: 0, w: 12, h: 6 }, panel: { ref: 'shared' } },
                        {
                            id: 's',
                            place: { x: 0, y: 6, w: 24, h: 3 },
                            panel: {
                                type: 'section',
                                title: 'More',
                                tiles: [
                                    {
                                        id: 'b',
                                        place: { x: 0, y: 0, w: 12, h: 6 },
                                        panel: { type: 'markdown', config: { text: 'Inside' } },
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
        })
    })

    it('keeps a bookmarked tab of a saved board while the board loads', async () => {
        const logic = dashboardV2Logic()
        logic.mount()

        router.actions.push(urls.dashboardV2Board('stored'), { tab: 'overview' })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.activeTab.id).toEqual('overview')
        expect(router.values.searchParams.tab).toEqual('overview')
    })

    it('stays on the fixture when going back to it before a board finishes loading', async () => {
        const logic = dashboardV2Logic()
        logic.mount()

        router.actions.push(urls.dashboardV2Board('stored'))
        router.actions.push(urls.dashboardV2())
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.boardUid).toBeNull()
        expect(logic.values.dashboard.title).not.toEqual('Stored board')
    })

    it('shows the problem instead of the fixture when the board in the URL is missing', async () => {
        const logic = dashboardV2Logic()
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
