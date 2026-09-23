import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import { getRouterContext } from 'kea-router/lib/router'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { osFrameSrc } from '../bridge/osFrame'
import {
    OsBounds,
    OsPoint,
    OsSize,
    OsSnapSide,
    clampBounds,
    maximizedBounds,
    placeNewWindow,
    snappedBounds,
    tidyLayout,
} from './osWindowGeometry'
import { OsWindowCommand } from './osWindowShortcuts'

export interface OsWindowState {
    id: string
    /** The window's regular app path with search and hash, always same-origin (see `osFrameSrc`). */
    path: string
    title: string
    bounds: OsBounds
    zIndex: number
    minimized: boolean
    maximized: boolean
    /** The bounds to go back to after a maximize or a snap. */
    restoreBounds: OsBounds | null
    /** Set when the window previews an App Store app: the app's catalog key. The store draws the preview bar. */
    preview?: string
}

export interface OsOpenWindowOptions {
    newWindow?: boolean
    title?: string
    /** The desktop point the window zooms open from, for example the icon that opened it. */
    origin?: OsPoint
    /** Marks a new window as a preview of this App Store app. */
    preview?: string
}

export interface OsDesktopState {
    windows: OsWindowState[]
    desktop: OsSize
}

export const OS_WINDOW_DEFAULT_TITLE = 'PostHog'

// pinned: localStorage key prefix, renaming it drops every saved desktop layout
const STORAGE_KEY_PREFIX = 'posthog-os-windows:'
// pinned: sessionStorage key prefix for the URL each tab showed last
const TAB_URL_KEY_PREFIX = 'posthog-os-windows-url:'
const STORAGE_VERSION = 1

function isFiniteNumber(value: unknown): value is number {
    return typeof value === 'number' && Number.isFinite(value)
}

function parseBounds(value: unknown): OsBounds | null {
    if (!value || typeof value !== 'object') {
        return null
    }
    const { x, y, width, height } = value as Record<string, unknown>
    return isFiniteNumber(x) && isFiniteNumber(y) && isFiniteNumber(width) && isFiniteNumber(height)
        ? { x, y, width, height }
        : null
}

function parseWindow(value: unknown): OsWindowState | null {
    if (!value || typeof value !== 'object') {
        return null
    }
    const raw = value as Record<string, unknown>
    const path = typeof raw.path === 'string' ? sanitizePath(raw.path) : null
    const bounds = parseBounds(raw.bounds)
    // The id becomes part of a frame name, so only short plain ids are allowed back in.
    if (typeof raw.id !== 'string' || !/^[a-z0-9]{1,16}$/.test(raw.id) || !path || !bounds) {
        return null
    }
    return {
        id: raw.id,
        path,
        title: typeof raw.title === 'string' && raw.title.trim() ? raw.title.slice(0, 200) : OS_WINDOW_DEFAULT_TITLE,
        bounds,
        zIndex: isFiniteNumber(raw.zIndex) ? raw.zIndex : 0,
        minimized: raw.minimized === true,
        maximized: raw.maximized === true,
        restoreBounds: parseBounds(raw.restoreBounds),
        ...(typeof raw.preview === 'string' && raw.preview ? { preview: raw.preview.slice(0, 200) } : {}),
    }
}

function readLayout(key: string | null): OsWindowState[] {
    const empty: OsWindowState[] = []
    if (!key) {
        return empty
    }
    try {
        const parsed = JSON.parse(localStorage.getItem(key) ?? 'null')
        if (!parsed || parsed.version !== STORAGE_VERSION || !Array.isArray(parsed.windows)) {
            return empty
        }
        const seen = new Set<string>()
        const windows = (parsed.windows as unknown[])
            .map(parseWindow)
            .filter((w): w is OsWindowState => !!w && !seen.has(w.id) && !!seen.add(w.id))
        const stack = [...windows].sort((a, b) => a.zIndex - b.zIndex).map((w) => w.id)
        return windows.map((w) => ({ ...w, zIndex: stack.indexOf(w.id) + 1 }))
    } catch {
        return empty
    }
}

// Tabs of one project share the layout, but each tab keeps its own last URL. Otherwise another tab's save
// would make this tab reopen a window it closed.
function readTabUrl(teamId: number | null): string | null {
    try {
        return teamId ? sessionStorage.getItem(`${TAB_URL_KEY_PREFIX}${teamId}`) : null
    } catch {
        return null
    }
}

function writeLayout(teamId: number | null, windows: OsWindowState[], url: string): void {
    if (!teamId) {
        return
    }
    try {
        localStorage.setItem(`${STORAGE_KEY_PREFIX}${teamId}`, JSON.stringify({ version: STORAGE_VERSION, windows }))
        sessionStorage.setItem(`${TAB_URL_KEY_PREFIX}${teamId}`, url)
    } catch {
        // A full or blocked localStorage only costs the saved layout, so the desktop keeps working.
    }
}

/** `/os` is the desktop without a window, so it never opens as one. */
function isDesktopUrl(url: string): boolean {
    return removeProjectIdIfPresent(url.split(/[?#]/)[0]) === urls.os()
}

function routerUrl(): string {
    const { pathname, search, hash } = router.values.location
    return `${pathname}${search}${hash}`
}

/**
 * Moves the address bar without a kea-router location change. A router change would make this page load
 * the window's scene itself: it would log a second pageview on every focus change, and a scene with its own
 * page layout (onboarding, login) would replace the whole OS shell.
 */
function replaceAddressBar(url: string): void {
    const history = getRouterContext().history ?? window.history
    history.replaceState(window.history.state, '', url)
}

function sanitizePath(path: string): string | null {
    try {
        // The whole input goes through `osFrameSrc` unparsed, so `//host/x` resolves to another origin and is refused.
        return osFrameSrc({ pathname: path, search: '', hash: '' }, window.location.origin)
    } catch {
        return null
    }
}

function newWindowId(): string {
    return Math.random().toString(36).slice(2, 10)
}

function topWindow(windows: OsWindowState[]): OsWindowState | null {
    return windows.reduce<OsWindowState | null>(
        (top, w) => (!w.minimized && (!top || w.zIndex > top.zIndex) ? w : top),
        null
    )
}

function raise(windows: OsWindowState[], id: string): OsWindowState[] {
    const order = [...windows].sort((a, b) => a.zIndex - b.zIndex).map((w) => w.id)
    const stack = [...order.filter((other) => other !== id), id]
    return windows.map((w) => ({ ...w, zIndex: stack.indexOf(w.id) + 1 }))
}

function updateIn(
    state: OsDesktopState,
    id: string,
    update: (w: OsWindowState) => Partial<OsWindowState>
): OsDesktopState {
    return { ...state, windows: state.windows.map((w) => (w.id === id ? { ...w, ...update(w) } : w)) }
}

function focusIn(state: OsDesktopState, id: string): OsDesktopState {
    // Every click inside a window asks for focus, so an already focused window keeps the same state.
    if (!state.windows.some((w) => w.id === id) || topWindow(state.windows)?.id === id) {
        return state
    }
    return { ...state, windows: raise(updateIn(state, id, () => ({ minimized: false })).windows, id) }
}

function initialDesktop(): OsSize {
    return { width: window.innerWidth, height: window.innerHeight }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface osWindowsLogicValues {
    currentTeamId: number | null // teamLogic
    desktop: OsSize
    focusedWindow: OsWindowState | null
    state: OsDesktopState
    windows: OsWindowState[]
    zoomOrigins: Record<string, OsPoint>
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface osWindowsLogicActions {
    closeWindow: (id: string) => {
        id: string
    }
    focusWindow: (id: string) => {
        id: string
    }
    maximizeWindow: (id: string) => {
        id: string
    }
    minimizeWindow: (id: string) => {
        id: string
    }
    openWindow: (
        path: string,
        options?: OsOpenWindowOptions
    ) => {
        id: string
        options: OsOpenWindowOptions
        path: string
    }
    restoreLayout: (windows: OsWindowState[]) => {
        windows: OsWindowState[]
    }
    restoreWindow: (id: string) => {
        id: string
    }
    runWindowCommand: (command: OsWindowCommand) => {
        command: OsWindowCommand
    }
    setDesktopSize: (desktop: OsSize) => {
        desktop: OsSize
    }
    setWindowBounds: (
        id: string,
        bounds: OsBounds
    ) => {
        bounds: OsBounds
        id: string
    }
    snapWindow: (
        id: string,
        side: OsSnapSide
    ) => {
        id: string
        side: OsSnapSide
    }
    tidyUpWindows: () => {
        value: true
    }
    unmaximizeWindow: (id: string) => {
        id: string
    }
    windowNavigated: (
        id: string,
        path: string,
        title?: string
    ) => {
        id: string
        path: string
        title: string | undefined
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface osWindowsLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        windows: (state: OsDesktopState) => OsWindowState[]
        desktop: (state: OsDesktopState) => OsSize
        focusedWindow: (windows: OsWindowState[]) => OsWindowState | null
    }
}

export type osWindowsLogicType = MakeLogicType<
    osWindowsLogicValues,
    osWindowsLogicActions,
    Record<string, any>,
    osWindowsLogicMeta
>

export const osWindowsLogic = kea<osWindowsLogicType>([
    path(['scenes', 'os', 'windows', 'osWindowsLogic']),
    connect(() => ({ values: [teamLogic, ['currentTeamId']] })),
    actions({
        openWindow: (path: string, options: OsOpenWindowOptions = {}) => ({ path, options, id: newWindowId() }),
        focusWindow: (id: string) => ({ id }),
        closeWindow: (id: string) => ({ id }),
        minimizeWindow: (id: string) => ({ id }),
        restoreWindow: (id: string) => ({ id }),
        windowNavigated: (id: string, path: string, title?: string) => ({ id, path, title }),
        setWindowBounds: (id: string, bounds: OsBounds) => ({ id, bounds }),
        maximizeWindow: (id: string) => ({ id }),
        unmaximizeWindow: (id: string) => ({ id }),
        snapWindow: (id: string, side: OsSnapSide) => ({ id, side }),
        tidyUpWindows: true,
        setDesktopSize: (desktop: OsSize) => ({ desktop }),
        restoreLayout: (windows: OsWindowState[]) => ({ windows }),
        runWindowCommand: (command: OsWindowCommand) => ({ command }),
    }),
    reducers({
        state: [
            { windows: [], desktop: initialDesktop() } as OsDesktopState,
            {
                openWindow: (state, { path, options, id }) => {
                    const safePath = sanitizePath(path)
                    if (!safePath) {
                        return state
                    }
                    const existing = options.newWindow ? null : state.windows.find((w) => w.path === safePath)
                    if (existing) {
                        return focusIn(state, existing.id)
                    }
                    const focused = topWindow(state.windows)
                    const created: OsWindowState = {
                        id,
                        path: safePath,
                        title: options.title ?? OS_WINDOW_DEFAULT_TITLE,
                        bounds: placeNewWindow(focused?.bounds ?? null, state.desktop),
                        zIndex: state.windows.length + 1,
                        minimized: false,
                        maximized: false,
                        restoreBounds: null,
                        ...(options.preview ? { preview: options.preview } : {}),
                    }
                    return { ...state, windows: raise([...state.windows, created], id) }
                },
                focusWindow: (state, { id }) => focusIn(state, id),
                restoreWindow: (state, { id }) => focusIn(state, id),
                closeWindow: (state, { id }) => ({ ...state, windows: state.windows.filter((w) => w.id !== id) }),
                minimizeWindow: (state, { id }) => updateIn(state, id, () => ({ minimized: true })),
                windowNavigated: (state, { id, path, title }) => {
                    const safePath = sanitizePath(path)
                    if (!safePath) {
                        return state
                    }
                    return updateIn(state, id, (w) => ({ path: safePath, title: title?.trim() || w.title }))
                },
                setWindowBounds: (state, { id, bounds }) =>
                    updateIn(state, id, () => ({
                        bounds: clampBounds(bounds, state.desktop),
                        maximized: false,
                        restoreBounds: null,
                    })),
                maximizeWindow: (state, { id }) =>
                    updateIn(state, id, (w) => ({
                        bounds: maximizedBounds(state.desktop),
                        maximized: true,
                        // A snapped window un-maximizes back into its half.
                        restoreBounds: w.maximized ? w.restoreBounds : w.bounds,
                    })),
                snapWindow: (state, { id, side }) =>
                    updateIn(state, id, (w) => ({
                        bounds: snappedBounds(side, state.desktop),
                        maximized: false,
                        restoreBounds: w.restoreBounds ?? w.bounds,
                    })),
                unmaximizeWindow: (state, { id }) =>
                    updateIn(state, id, (w) => ({
                        bounds: w.restoreBounds ? clampBounds(w.restoreBounds, state.desktop) : w.bounds,
                        maximized: false,
                        restoreBounds: null,
                    })),
                tidyUpWindows: (state) => {
                    const visible = state.windows
                        .filter((w) => !w.minimized)
                        .sort((a, b) => {
                            const boundsA = a.restoreBounds ?? a.bounds
                            const boundsB = b.restoreBounds ?? b.bounds
                            return boundsA.x - boundsB.x || boundsA.y - boundsB.y
                        })
                    const cells = tidyLayout(visible.length, state.desktop)
                    const cellFor = new Map(visible.map((w, index) => [w.id, cells[index]]))
                    return {
                        ...state,
                        windows: state.windows.map((w) => {
                            const cell = cellFor.get(w.id)
                            return cell ? { ...w, bounds: cell, maximized: false, restoreBounds: null } : w
                        }),
                    }
                },
                restoreLayout: (state, { windows }) => ({ ...state, windows }),
                setDesktopSize: (state, { desktop }) => ({ ...state, desktop }),
            },
        ],
        // Not saved: a restored window has no icon to zoom from.
        zoomOrigins: [
            {} as Record<string, OsPoint>,
            {
                openWindow: (origins, { id, options }) =>
                    options.origin ? { ...origins, [id]: options.origin } : origins,
                closeWindow: (origins, { id }) => {
                    const { [id]: _closed, ...rest } = origins
                    return rest
                },
            },
        ],
    }),
    selectors({
        // State keeps the bounds a window asked for, so a desktop that shrinks and grows back restores them.
        windows: [
            (s) => [s.state],
            (state: OsDesktopState): OsWindowState[] =>
                state.windows.map((w) => ({
                    ...w,
                    bounds: w.maximized ? maximizedBounds(state.desktop) : clampBounds(w.bounds, state.desktop),
                })),
        ],
        desktop: [(s) => [s.state], (state: OsDesktopState): OsSize => state.desktop],
        focusedWindow: [(s) => [s.windows], (windows: OsWindowState[]): OsWindowState | null => topWindow(windows)],
    }),
    listeners(({ actions, values, cache }) => {
        const persist = (): void => {
            writeLayout(values.currentTeamId, values.state.windows, cache.pageUrl)
        }
        const syncUrl = (): void => {
            const focused = values.focusedWindow
            if (focused && focused.path !== cache.pageUrl) {
                cache.pageUrl = focused.path
                replaceAddressBar(focused.path)
            }
            if (focused) {
                // The page's own scene does not follow the address bar, so the tab title follows the window.
                document.title =
                    focused.title === OS_WINDOW_DEFAULT_TITLE
                        ? focused.title
                        : `${focused.title} • ${OS_WINDOW_DEFAULT_TITLE}`
            }
            persist()
        }
        return {
            openWindow: syncUrl,
            focusWindow: syncUrl,
            restoreWindow: syncUrl,
            closeWindow: syncUrl,
            minimizeWindow: syncUrl,
            windowNavigated: syncUrl,
            setWindowBounds: persist,
            maximizeWindow: persist,
            unmaximizeWindow: persist,
            snapWindow: persist,
            tidyUpWindows: persist,
            runWindowCommand: ({ command }) => {
                if (command === 'tidy-up') {
                    actions.tidyUpWindows()
                    return
                }
                const focused = values.focusedWindow
                if (!focused) {
                    return
                }
                if (command === 'snap-left' || command === 'snap-right') {
                    actions.snapWindow(focused.id, command === 'snap-left' ? 'left' : 'right')
                } else if (command === 'toggle-maximize') {
                    if (focused.maximized) {
                        actions.unmaximizeWindow(focused.id)
                    } else {
                        actions.maximizeWindow(focused.id)
                    }
                } else if (command === 'minimize') {
                    actions.minimizeWindow(focused.id)
                } else if (command === 'close') {
                    actions.closeWindow(focused.id)
                }
            },
            [router.actionTypes.locationChanged]: ({ method }) => {
                const url = routerUrl()
                cache.pageUrl = url
                // Only a push or a back/forward is a request to show a path. A replace is a redirect, and
                // the window that shows the page runs that redirect itself.
                if (method === 'REPLACE') {
                    return
                }
                if (url !== values.focusedWindow?.path && !isDesktopUrl(url)) {
                    actions.openWindow(url)
                }
            },
        }
    }),
    afterMount(({ actions, values, cache }) => {
        const url = routerUrl()
        cache.pageUrl = url
        const lastTabUrl = readTabUrl(values.currentTeamId)
        actions.restoreLayout(readLayout(values.currentTeamId ? `${STORAGE_KEY_PREFIX}${values.currentTeamId}` : null))
        // When the tab loads on the URL it showed last, the layout already shows it, or the user closed its
        // window, so only a different URL opens a window.
        if (url !== lastTabUrl && !isDesktopUrl(url)) {
            actions.openWindow(url)
        }
    }),
])
