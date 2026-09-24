import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { osWindowFramesLogic } from './osWindowFramesLogic'
import { osWindowsLogic } from './osWindowsLogic'

const INSIGHTS = `/project/${MOCK_TEAM_ID}/insights`
const REPLAY = `/project/${MOCK_TEAM_ID}/replay/home`
const FLAGS = `/project/${MOCK_TEAM_ID}/feature_flags`
const SQL = `/project/${MOCK_TEAM_ID}/sql`

describe('osWindowFramesLogic', () => {
    let windows: ReturnType<typeof osWindowsLogic.build>
    let frames: ReturnType<typeof osWindowFramesLogic.build>

    function mountAt(url: string): void {
        router.actions.push(url)
        windows = osWindowsLogic()
        windows.mount()
        frames = osWindowFramesLogic()
        frames.mount()
    }

    function idOf(path: string): string {
        const found = windows.values.windows.find((w) => w.path === path)
        if (!found) {
            throw new Error(`no window at ${path}`)
        }
        return found.id
    }

    function statuses(): Record<string, string> {
        return Object.fromEntries(windows.values.windows.map((w) => [w.path, frames.values.frameStatus[w.id]]))
    }

    beforeEach(() => {
        localStorage.clear()
        sessionStorage.clear()
        initKeaTests(true)
    })

    afterEach(() => {
        frames?.unmount()
        windows?.unmount()
    })

    it('shows a new window as loading until its app reports its first page, then as ready', () => {
        mountAt(INSIGHTS)

        expect(frames.values.frameStatus[idOf(INSIGHTS)]).toEqual('loading')

        windows.actions.windowNavigated(idOf(INSIGHTS), INSIGHTS, 'Insights')

        expect(frames.values.frameStatus[idOf(INSIGHTS)]).toEqual('ready')
    })

    function reloadWithFourWindows(): void {
        mountAt(INSIGHTS)
        for (const path of [REPLAY, FLAGS, SQL]) {
            windows.actions.openWindow(path)
        }
        for (const path of [INSIGHTS, REPLAY, FLAGS, SQL]) {
            windows.actions.windowNavigated(idOf(path), path)
        }
        frames.unmount()
        windows.unmount()
        mountAt(`/project/${MOCK_TEAM_ID}/os`)
    }

    it('after a reload, loads the top two windows first, and starts the next one when a frame loads', () => {
        reloadWithFourWindows()

        expect(statuses()).toEqual({ [INSIGHTS]: 'queued', [REPLAY]: 'queued', [FLAGS]: 'loading', [SQL]: 'loading' })

        windows.actions.windowNavigated(idOf(SQL), SQL)

        expect(statuses()).toEqual({ [INSIGHTS]: 'queued', [REPLAY]: 'loading', [FLAGS]: 'loading', [SQL]: 'ready' })
    })

    it('loads a window as soon as it comes to the front, also while two frames load', () => {
        reloadWithFourWindows()

        windows.actions.focusWindow(idOf(INSIGHTS))

        expect(statuses()).toEqual({ [INSIGHTS]: 'loading', [REPLAY]: 'queued', [FLAGS]: 'loading', [SQL]: 'loading' })

        windows.actions.openWindow(`/project/${MOCK_TEAM_ID}/dashboard`)

        expect(frames.values.frameStatus[idOf(`/project/${MOCK_TEAM_ID}/dashboard`)]).toEqual('loading')
    })

    it('treats a page that is not the app, such as an error page or another site, as loaded', () => {
        mountAt(INSIGHTS)

        frames.actions.framePageLoaded(idOf(INSIGHTS))

        expect(statuses()).toEqual({ [INSIGHTS]: 'ready' })
    })

    it('loads a minimized window only when it is restored, and keeps a loaded frame while minimized', () => {
        mountAt(INSIGHTS)
        windows.actions.openWindow(REPLAY)
        windows.actions.minimizeWindow(idOf(REPLAY))
        windows.actions.windowNavigated(idOf(INSIGHTS), INSIGHTS)
        windows.actions.openWindow(FLAGS)
        windows.actions.minimizeWindow(idOf(FLAGS))
        windows.actions.minimizeWindow(idOf(INSIGHTS))

        expect(statuses()).toEqual({ [INSIGHTS]: 'ready', [REPLAY]: 'loading', [FLAGS]: 'loading' })

        windows.unmount()
        frames.unmount()
        mountAt(`/project/${MOCK_TEAM_ID}/os`)

        expect(statuses()).toEqual({ [INSIGHTS]: 'queued', [REPLAY]: 'queued', [FLAGS]: 'queued' })

        windows.actions.restoreWindow(idOf(REPLAY))

        expect(statuses()).toEqual({ [INSIGHTS]: 'queued', [REPLAY]: 'loading', [FLAGS]: 'queued' })
    })

    it('marks a frame as slow after 20 seconds, lets the next window load, and reloads it on request', () => {
        jest.useFakeTimers()
        try {
            mountAt(INSIGHTS)
            jest.advanceTimersByTime(19_000)

            expect(statuses()).toEqual({ [INSIGHTS]: 'loading' })

            jest.advanceTimersByTime(1_000)
            windows.actions.openWindow(REPLAY)
            windows.actions.openWindow(FLAGS)

            expect(statuses()).toEqual({ [INSIGHTS]: 'slow', [REPLAY]: 'loading', [FLAGS]: 'loading' })

            const firstAttempt = frames.values.frameAttempts[idOf(INSIGHTS)]
            frames.actions.reloadFrame(idOf(INSIGHTS))

            expect(statuses()).toEqual({ [INSIGHTS]: 'loading', [REPLAY]: 'loading', [FLAGS]: 'loading' })
            expect(frames.values.frameAttempts[idOf(INSIGHTS)]).not.toEqual(firstAttempt)

            jest.advanceTimersByTime(20_000)

            expect(statuses()).toEqual({ [INSIGHTS]: 'slow', [REPLAY]: 'slow', [FLAGS]: 'slow' })

            windows.actions.windowNavigated(idOf(INSIGHTS), INSIGHTS)

            expect(statuses()).toEqual({ [INSIGHTS]: 'ready', [REPLAY]: 'slow', [FLAGS]: 'slow' })
        } finally {
            jest.useRealTimers()
        }
    })

    it('starts the next queued window when a loading window closes', () => {
        reloadWithFourWindows()

        windows.actions.closeWindow(idOf(FLAGS))

        expect(statuses()).toEqual({ [INSIGHTS]: 'queued', [REPLAY]: 'loading', [SQL]: 'loading' })
    })
})
