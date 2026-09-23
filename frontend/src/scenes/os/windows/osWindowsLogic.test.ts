import { MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { getRouterContext } from 'kea-router/lib/router'

import { initKeaTests } from '~/test/init'

import { osWindowsLogic } from './osWindowsLogic'

const INSIGHTS = `/project/${MOCK_TEAM_ID}/insights`
const REPLAY = `/project/${MOCK_TEAM_ID}/replay/home`
const FLAGS = `/project/${MOCK_TEAM_ID}/feature_flags?tab=overview#panel=discussion`

// The OS moves the address bar without kea-router, so `router.values.location` can lag behind it.
let addressBar = ''

function currentUrl(): string {
    return addressBar
}

function initKeaAndTrackAddressBar(team = MOCK_DEFAULT_TEAM): void {
    initKeaTests(true, team)
    const history = getRouterContext().history as History
    for (const method of ['pushState', 'replaceState'] as const) {
        const original = history[method].bind(history)
        history[method] = (state: any, title: string, url?: string | URL | null): void => {
            addressBar = String(url)
            original(state, title, url)
        }
    }
}

describe('osWindowsLogic', () => {
    let logic: ReturnType<typeof osWindowsLogic.build>

    function mountAt(url: string): void {
        router.actions.push(url)
        logic = osWindowsLogic()
        logic.mount()
    }

    function windowAt(path: string): ReturnType<typeof osWindowsLogic.build>['values']['windows'][number] {
        const found = logic.values.windows.find((w) => w.path === path)
        if (!found) {
            throw new Error(`no window at ${path}`)
        }
        return found
    }

    beforeEach(() => {
        localStorage.clear()
        sessionStorage.clear()
        initKeaAndTrackAddressBar()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('opens the URL the page loaded on as the focused window', () => {
        mountAt(INSIGHTS)

        expect(logic.values.windows.map((w) => w.path)).toEqual([INSIGHTS])
        expect(logic.values.focusedWindow?.path).toEqual(INSIGHTS)
    })

    it('focuses the newest window and keeps the browser URL on the focused window', () => {
        mountAt(INSIGHTS)

        logic.actions.openWindow(FLAGS)

        expect(logic.values.focusedWindow?.path).toEqual(FLAGS)
        expect(currentUrl()).toEqual(FLAGS)

        logic.actions.focusWindow(windowAt(INSIGHTS).id)

        expect(logic.values.focusedWindow?.path).toEqual(INSIGHTS)
        expect(currentUrl()).toEqual(INSIGHTS)
    })

    it.each([
        ['focuses the window that already shows the path', {}, 2],
        ['opens a second window when asked for a new one', { newWindow: true }, 3],
    ])('opening an open path %s', (_description, options, expectedCount) => {
        mountAt(INSIGHTS)
        logic.actions.openWindow(REPLAY)

        logic.actions.openWindow(INSIGHTS, options)

        expect(logic.values.windows).toHaveLength(expectedCount)
        expect(logic.values.focusedWindow?.path).toEqual(INSIGHTS)
    })

    it.each([
        ['a protocol-relative URL', '//evil.example.com/login'],
        ['an absolute URL on another site', 'https://evil.example.com/login'],
        ['a script URL', 'javascript:alert(1)'],
    ])('refuses to open %s', (_description, path) => {
        mountAt(INSIGHTS)

        logic.actions.openWindow(path)

        expect(logic.values.windows.map((w) => w.path)).toEqual([INSIGHTS])
    })

    it('hands focus and the URL to the window below when the focused window closes or minimizes', () => {
        mountAt(INSIGHTS)
        logic.actions.openWindow(REPLAY)
        logic.actions.openWindow(FLAGS)

        logic.actions.closeWindow(windowAt(FLAGS).id)

        expect(logic.values.windows.map((w) => w.path)).toEqual([INSIGHTS, REPLAY])
        expect(currentUrl()).toEqual(REPLAY)

        logic.actions.minimizeWindow(windowAt(REPLAY).id)

        expect(windowAt(REPLAY).minimized).toBe(true)
        expect(logic.values.focusedWindow?.path).toEqual(INSIGHTS)
        expect(currentUrl()).toEqual(INSIGHTS)

        logic.actions.restoreWindow(windowAt(REPLAY).id)

        expect(windowAt(REPLAY).minimized).toBe(false)
        expect(logic.values.focusedWindow?.path).toEqual(REPLAY)
        expect(currentUrl()).toEqual(REPLAY)
    })

    it('moves the URL without a router location change, so the page does not load the scene itself', () => {
        mountAt(INSIGHTS)

        logic.actions.openWindow(REPLAY)
        logic.actions.windowNavigated(windowAt(REPLAY).id, `/project/${MOCK_TEAM_ID}/onboarding/replay`)

        expect(currentUrl()).toEqual(`/project/${MOCK_TEAM_ID}/onboarding/replay`)
        expect(router.values.location.pathname).toEqual(INSIGHTS)
    })

    it('leaves the URL alone when the last visible window goes away', () => {
        mountAt(INSIGHTS)

        logic.actions.minimizeWindow(windowAt(INSIGHTS).id)

        expect(logic.values.focusedWindow).toBeNull()
        expect(currentUrl()).toEqual(INSIGHTS)
    })

    it('opens a path the page navigates to, and ignores redirects it did not ask for', () => {
        mountAt(INSIGHTS)

        router.actions.push(REPLAY)

        expect(logic.values.windows.map((w) => w.path)).toEqual([INSIGHTS, REPLAY])
        expect(logic.values.focusedWindow?.path).toEqual(REPLAY)

        router.actions.replace(FLAGS)

        expect(logic.values.windows.map((w) => w.path)).toEqual([INSIGHTS, REPLAY])
    })

    it('follows navigation inside a window, and moves the URL only for the focused one', () => {
        mountAt(INSIGHTS)
        logic.actions.openWindow(REPLAY)

        logic.actions.windowNavigated(windowAt(INSIGHTS).id, `${INSIGHTS}/new`, 'New insight')

        expect(windowAt(`${INSIGHTS}/new`).title).toEqual('New insight')
        expect(currentUrl()).toEqual(REPLAY)

        logic.actions.windowNavigated(windowAt(REPLAY).id, `${REPLAY}?filter=1`, 'Replay')

        expect(currentUrl()).toEqual(`${REPLAY}?filter=1`)
    })

    it('maximizes and snaps a window, and goes back to the size it had before', () => {
        mountAt(INSIGHTS)
        logic.actions.setDesktopSize({ width: 1600, height: 900 })
        const id = windowAt(INSIGHTS).id
        logic.actions.setWindowBounds(id, { x: 100, y: 50, width: 800, height: 600 })

        logic.actions.maximizeWindow(id)

        expect(windowAt(INSIGHTS)).toMatchObject({ maximized: true, bounds: { x: 0, y: 0, width: 1600, height: 900 } })

        logic.actions.unmaximizeWindow(id)

        expect(windowAt(INSIGHTS)).toMatchObject({
            maximized: false,
            bounds: { x: 100, y: 50, width: 800, height: 600 },
        })

        logic.actions.snapWindow(id, 'right')

        expect(windowAt(INSIGHTS).bounds).toEqual({ x: 800, y: 0, width: 800, height: 900 })

        logic.actions.unmaximizeWindow(id)

        expect(windowAt(INSIGHTS).bounds).toEqual({ x: 100, y: 50, width: 800, height: 600 })
    })

    it('keeps a maximized window filling the desktop and a moved window reachable when the desktop shrinks', () => {
        mountAt(INSIGHTS)
        logic.actions.openWindow(REPLAY)
        logic.actions.setDesktopSize({ width: 1600, height: 900 })
        logic.actions.maximizeWindow(windowAt(INSIGHTS).id)
        logic.actions.setWindowBounds(windowAt(REPLAY).id, { x: 1400, y: 700, width: 800, height: 600 })

        logic.actions.setDesktopSize({ width: 1000, height: 700 })

        expect(windowAt(INSIGHTS).bounds).toEqual({ x: 0, y: 0, width: 1000, height: 700 })
        const replay = windowAt(REPLAY).bounds
        expect(replay.x).toBeLessThanOrEqual(1000 - 160)
        expect(replay.y).toBeLessThanOrEqual(700 - 80)

        logic.actions.setDesktopSize({ width: 1600, height: 900 })

        expect(windowAt(REPLAY).bounds).toEqual({ x: 1400, y: 700, width: 800, height: 600 })
    })

    it('tidies the visible windows into a grid in their left-to-right order and leaves minimized ones alone', () => {
        mountAt(INSIGHTS)
        logic.actions.openWindow(REPLAY)
        logic.actions.openWindow(FLAGS)
        logic.actions.setDesktopSize({ width: 1000, height: 600 })
        logic.actions.setWindowBounds(windowAt(REPLAY).id, { x: 10, y: 10, width: 400, height: 300 })
        logic.actions.setWindowBounds(windowAt(INSIGHTS).id, { x: 500, y: 10, width: 400, height: 300 })
        logic.actions.maximizeWindow(windowAt(INSIGHTS).id)
        logic.actions.minimizeWindow(windowAt(FLAGS).id)
        const flagsBefore = windowAt(FLAGS).bounds

        logic.actions.tidyUpWindows()

        expect(windowAt(REPLAY).bounds).toEqual({ x: 8, y: 8, width: 488, height: 584 })
        expect(windowAt(INSIGHTS)).toMatchObject({
            maximized: false,
            bounds: { x: 504, y: 8, width: 488, height: 584 },
        })
        expect(windowAt(FLAGS).bounds).toEqual(flagsBefore)
    })

    it('runs keyboard commands on the focused window only', () => {
        mountAt(INSIGHTS)
        logic.actions.setDesktopSize({ width: 1000, height: 600 })
        logic.actions.openWindow(REPLAY)

        logic.actions.runWindowCommand('snap-left')
        logic.actions.runWindowCommand('toggle-maximize')

        expect(windowAt(REPLAY).maximized).toBe(true)

        logic.actions.runWindowCommand('toggle-maximize')

        expect(windowAt(REPLAY)).toMatchObject({ maximized: false, bounds: { x: 0, y: 0, width: 500, height: 600 } })

        logic.actions.runWindowCommand('close')

        expect(logic.values.windows.map((w) => w.path)).toEqual([INSIGHTS])
    })

    it('shows no window on the empty desktop route', () => {
        mountAt(`/project/${MOCK_TEAM_ID}/os`)

        expect(logic.values.windows).toEqual([])
    })

    describe('after a reload', () => {
        function reloadAt(url: string, team = MOCK_DEFAULT_TEAM): void {
            logic.unmount()
            initKeaAndTrackAddressBar(team)
            mountAt(url)
            logic.actions.setDesktopSize({ width: 1600, height: 900 })
        }

        function arrangeThreeWindows(): void {
            mountAt(INSIGHTS)
            logic.actions.setDesktopSize({ width: 1600, height: 900 })
            logic.actions.openWindow(REPLAY, { preview: 'Session replay' })
            logic.actions.openWindow(FLAGS)
            logic.actions.setWindowBounds(windowAt(INSIGHTS).id, { x: 40, y: 30, width: 700, height: 500 })
            logic.actions.snapWindow(windowAt(REPLAY).id, 'right')
            logic.actions.minimizeWindow(windowAt(FLAGS).id)
            logic.actions.focusWindow(windowAt(INSIGHTS).id)
        }

        function layout(): Array<Record<string, unknown>> {
            return logic.values.windows.map(
                ({ path, title, bounds, zIndex, minimized, maximized, restoreBounds, preview }) => ({
                    path,
                    title,
                    bounds,
                    zIndex,
                    minimized,
                    maximized,
                    restoreBounds,
                    preview,
                })
            )
        }

        it('restores the same layout on the same URL', () => {
            arrangeThreeWindows()
            const before = layout()

            reloadAt(INSIGHTS)

            expect(layout()).toEqual(before)
            expect(layout().map((w) => w.preview)).toEqual([undefined, 'Session replay', undefined])
            expect(logic.values.focusedWindow?.path).toEqual(INSIGHTS)
        })

        it('opens a deep link as the focused window on top of the restored layout', () => {
            arrangeThreeWindows()

            reloadAt(`/project/${MOCK_TEAM_ID}/dashboard`)

            expect(logic.values.windows.map((w) => w.path)).toEqual([
                INSIGHTS,
                REPLAY,
                FLAGS,
                `/project/${MOCK_TEAM_ID}/dashboard`,
            ])
            expect(logic.values.focusedWindow?.path).toEqual(`/project/${MOCK_TEAM_ID}/dashboard`)
        })

        it('brings back a minimized window when the URL points at it', () => {
            arrangeThreeWindows()

            reloadAt(FLAGS)

            expect(logic.values.windows).toHaveLength(3)
            expect(logic.values.focusedWindow?.path).toEqual(FLAGS)
        })

        it('does not reopen a window that was closed on the URL it left behind', () => {
            mountAt(INSIGHTS)
            logic.actions.closeWindow(windowAt(INSIGHTS).id)

            reloadAt(INSIGHTS)

            expect(logic.values.windows).toEqual([])
        })

        it('does not reopen the closed window when another tab saved the layout since', () => {
            mountAt(INSIGHTS)
            logic.actions.closeWindow(windowAt(INSIGHTS).id)
            const key = `posthog-os-windows:${MOCK_TEAM_ID}`
            const saved = JSON.parse(localStorage.getItem(key) ?? '{}')
            localStorage.setItem(key, JSON.stringify({ ...saved, url: REPLAY }))

            reloadAt(INSIGHTS)

            expect(logic.values.windows).toEqual([])
        })

        it('keeps each project on its own desktop', () => {
            arrangeThreeWindows()

            reloadAt('/project/998/insights', { ...MOCK_DEFAULT_TEAM, id: 998 })

            expect(logic.values.windows.map((w) => w.path)).toEqual(['/project/998/insights'])
        })

        it.each([
            ['is not JSON', '{not json'],
            ['has the wrong shape', JSON.stringify({ windows: 'nope' })],
            [
                'points a window at another site',
                JSON.stringify({
                    version: 1,
                    url: '/x',
                    windows: [
                        {
                            id: 'evil',
                            path: '//evil.example.com/login',
                            title: 'Login',
                            bounds: { x: 0, y: 0, width: 800, height: 600 },
                            zIndex: 1,
                            minimized: false,
                            maximized: false,
                            restoreBounds: null,
                        },
                    ],
                }),
            ],
        ])('starts from the URL alone when the saved layout %s', (_description, stored) => {
            localStorage.setItem(`posthog-os-windows:${MOCK_TEAM_ID}`, stored)

            mountAt(INSIGHTS)

            expect(logic.values.windows.map((w) => w.path)).toEqual([INSIGHTS])
        })
    })
})
