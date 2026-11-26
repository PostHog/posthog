import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { CURRENT_SCHEMA_VERSION, UnreadableBoardError, upgradeBoard } from './dashboard/boardSchema'
import { dashboardV2Logic } from './dashboardV2Logic'

// A board as a newer client could store it: a field this client doesn't know sits at every level.
const STORED_BOARD = {
    version: 2,
    title: 'Stored board',
    boardFromTheFuture: { kept: true },
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
                    widget: { type: 'markdown', config: { text: 'Hello' }, widgetFromTheFuture: ['b'] },
                },
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
        // The viewer's level comes from access control, never from the stored board.
        logic.actions.commitDashboard({ ...logic.values.dashboard, user_access_level: AccessControlLevel.Editor })

        logic.actions.applyDashboardEdit({ edit: 'addTab', title: 'Another' })
        logic.actions.saveAsBoard()
        await expectLogic(logic).toFinishAllListeners()

        expect(savedSpec.boardFromTheFuture).toEqual({ kept: true })
        expect(savedSpec.tabs[0].tabFromTheFuture).toEqual(1)
        expect(savedSpec.tabs[0].tiles[0].tileFromTheFuture).toEqual('a')
        expect(savedSpec.tabs[0].tiles[0].widget.widgetFromTheFuture).toEqual(['b'])
        expect(savedSpec.tabs).toHaveLength(2)
        expect(savedSpec).not.toHaveProperty('user_access_level')
        expect(router.values.location.pathname).toContain(urls.dashboardV2Board('copy'))
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
    ])('refuses to load %s', (_name, stored) => {
        expect(() => upgradeBoard(stored)).toThrow(UnreadableBoardError)
    })
})
