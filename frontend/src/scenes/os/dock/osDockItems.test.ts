import { OsApp } from '../store/osAppCatalog'
import { OsWindowState } from '../windows/osWindowsLogic'
import { osAppForPath, osDockClickAction, osDockItems } from './osDockItems'

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
const apps = [productAnalytics, sessionReplay, clusters, llmAnalytics]

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

describe('osDockItems', () => {
    it('shows one item per open window in the order they opened, and marks the focused one', () => {
        const windows = [
            osWindow('w1', '/project/1/insights/abc', { zIndex: 3 }),
            osWindow('w2', '/project/1/replay/xyz?filters=1', { zIndex: 1, minimized: true }),
            osWindow('w3', '/project/1/persons/abc', { zIndex: 2 }),
        ]

        const dock = osDockItems(windows, 'w1', apps)

        expect(
            dock.windows.map((item) => [item.windowId, item.title, item.app?.key ?? null, item.focused, item.minimized])
        ).toEqual([
            ['w1', 'Title w1', 'Product analytics', true, false],
            ['w2', 'Title w2', 'Session replay', false, true],
            ['w3', 'Title w3', null, false, false],
        ])
    })

    it('shows only the App Store when no window is open', () => {
        expect(osDockItems([], null, apps)).toEqual({
            store: { windowId: null, focused: false, minimized: false },
            windows: [],
        })
    })

    it('puts the top App Store window on the App Store item, not in the window list', () => {
        const windows = [
            osWindow('w1', '/project/1/app-store/surveys', { zIndex: 1, minimized: true }),
            osWindow('w2', '/project/1/app-store', { zIndex: 2 }),
            osWindow('w3', '/project/1/insights', { zIndex: 3 }),
        ]

        const dock = osDockItems(windows, 'w3', apps)

        expect(dock.store).toEqual({ windowId: 'w2', focused: false, minimized: false })
        expect(dock.windows.map((item) => item.windowId)).toEqual(['w1', 'w3'])
    })

    it.each([
        ['restores a minimized window', { focused: false, minimized: true }, 'restore'],
        ['focuses a window in the background', { focused: false, minimized: false }, 'focus'],
        ['minimizes the focused window', { focused: true, minimized: false }, 'minimize'],
    ] as const)('%s on click', (_, state, expected) => {
        expect(osDockClickAction(state)).toEqual(expected)
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
