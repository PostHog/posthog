import { OsApp } from '../store/osAppCatalog'
import { OsWindowState } from '../windows/osWindowsLogic'
import { OS_DOCK_STORE_KEY, OsDockItem, osAppForPath, osDockClick, osDockItems } from './osDockItems'

const app = (key: string, href: string): OsApp => ({
    key,
    name: key,
    slug: key.toLowerCase(),
    href,
    description: null,
    status: 'released',
    job: 'understand',
    system: false,
})

const productAnalytics = app('Product analytics', '/insights')
const sessionReplay = app('Session replay', '/replay/home')
const clusters = app('Clusters', '/ai-observability/clusters')
const llmAnalytics = app('LLM analytics', '/ai-observability/dashboard')
const surveys = app('Surveys', '/surveys')
const apps = [productAnalytics, sessionReplay, clusters, llmAnalytics, surveys]

const osWindow = (id: string, path: string, extra: Partial<OsWindowState> = {}): OsWindowState => ({
    id,
    path,
    title: `Title ${id}`,
    bounds: { x: 0, y: 0, width: 800, height: 600 },
    zIndex: 1,
    minimized: false,
    maximized: false,
    restoreBounds: null,
    ...extra,
})

type Row = [key: string, title: string, windowIds: string[], pinned: boolean, focused: boolean, minimized: boolean]
const rows = (items: OsDockItem[]): Row[] =>
    items.map((item) => [item.key, item.title, item.windowIds, item.pinned, item.focused, item.minimized])

describe('osDockItems', () => {
    it('shows one item per open app in the order its first window opened, and a window no app claims on its own', () => {
        const windows = [
            osWindow('w1', '/project/1/insights/abc', { zIndex: 4 }),
            osWindow('w2', '/project/1/replay/xyz?filters=1', { zIndex: 1, minimized: true }),
            osWindow('w3', '/project/1/persons/abc', { zIndex: 2 }),
            osWindow('w4', '/project/1/insights/new', { zIndex: 3 }),
        ]

        expect(rows(osDockItems(windows, 'w1', apps, []).apps)).toEqual([
            ['Product analytics', 'Product analytics', ['w1', 'w4'], false, true, false],
            ['Session replay', 'Session replay', ['w2'], false, false, true],
            ['window:w3', 'Title w3', ['w3'], false, false, false],
        ])
    })

    it('drops an app when its last window closes, and moves a window to the app it navigates to', () => {
        const before = [osWindow('w1', '/project/1/insights/abc'), osWindow('w2', '/project/1/surveys')]
        const after = [osWindow('w2', '/project/1/replay/home')]

        expect(osDockItems(before, 'w2', apps, []).apps.map((item) => item.key)).toEqual([
            'Product analytics',
            'Surveys',
        ])
        expect(osDockItems(after, 'w2', apps, []).apps.map((item) => item.key)).toEqual(['Session replay'])
    })

    it('keeps pinned apps first in pin order with or without a window, and hides pins no known app matches', () => {
        const windows = [osWindow('w1', '/project/1/insights'), osWindow('w2', '/project/1/replay/home')]

        const dock = osDockItems(windows, null, apps, ['Surveys', 'Removed app', 'Session replay'])

        expect(rows(dock.apps)).toEqual([
            ['Surveys', 'Surveys', [], true, false, false],
            ['Session replay', 'Session replay', ['w2'], true, false, false],
            ['Product analytics', 'Product analytics', ['w1'], false, false, false],
        ])
    })

    it('shows only the App Store when no window is open and nothing is pinned', () => {
        const dock = osDockItems([], null, apps, [])

        expect(rows([dock.store])).toEqual([[OS_DOCK_STORE_KEY, 'App Store', [], false, false, false]])
        expect(dock.apps).toEqual([])
    })

    it('puts every App Store window on the App Store item', () => {
        const windows = [
            osWindow('w1', '/project/1/app-store/surveys', { zIndex: 1, minimized: true }),
            osWindow('w2', '/project/1/insights', { zIndex: 3 }),
            osWindow('w3', '/project/1/app-store', { zIndex: 2, minimized: true }),
        ]

        const dock = osDockItems(windows, 'w2', apps, [])

        expect(rows([dock.store])).toEqual([[OS_DOCK_STORE_KEY, 'App Store', ['w1', 'w3'], false, false, true]])
        expect(dock.apps.map((item) => item.key)).toEqual(['Product analytics'])
    })

    it.each([
        ['opens an app with no window', [], null, { action: 'open' }],
        [
            'restores the top window when every window is minimized',
            [
                osWindow('a', '/insights', { zIndex: 1, minimized: true }),
                osWindow('b', '/insights/new', { zIndex: 2, minimized: true }),
            ],
            null,
            { action: 'restore', windowId: 'b' },
        ],
        [
            'focuses the top visible window when the app is in the background',
            [
                osWindow('a', '/insights', { zIndex: 1 }),
                osWindow('b', '/insights/new', { zIndex: 3, minimized: true }),
                osWindow('other', '/surveys', { zIndex: 2 }),
            ],
            'other',
            { action: 'focus', windowId: 'a' },
        ],
        [
            'minimizes the focused window when the app is in front',
            [osWindow('a', '/insights', { zIndex: 1 }), osWindow('b', '/insights/new', { zIndex: 2 })],
            'b',
            { action: 'minimize', windowId: 'b' },
        ],
    ] as const)('%s on click', (_, windows, focusedId, expected) => {
        const item = osDockItems([...windows], focusedId, apps, ['Product analytics']).apps[0]

        expect(osDockClick(item, [...windows])).toEqual(expected)
    })

    it.each([
        ['/project/1/insights/abc', 'Product analytics'],
        ['/project/1/replay/xyz', 'Session replay'],
        ['/project/1/persons/abc', null],
        ['/project/1/ai-observability/clusters/abc', 'Clusters'],
        ['/project/1/ai-observability/traces/abc', null],
    ])('finds the app of %s for its icon', (path, expected) => {
        expect(osAppForPath(path, apps)?.key ?? null).toEqual(expected)
    })
})
