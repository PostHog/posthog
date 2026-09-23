import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import type { OsApp } from '../store/osAppCatalog'
import type { OsWindowState } from '../windows/osWindowsLogic'

export interface OsDockWindowState {
    focused: boolean
    minimized: boolean
}

export interface OsDockWindowItem extends OsDockWindowState {
    windowId: string
    title: string
    /** The app the window belongs to, for its icon. Null for a page no app claims, such as a person. */
    app: OsApp | null
}

export interface OsDockStoreItem extends OsDockWindowState {
    windowId: string | null
}

export interface OsDockItems {
    store: OsDockStoreItem
    windows: OsDockWindowItem[]
}

export type OsDockClickAction = 'restore' | 'focus' | 'minimize'

function pathnameOf(path: string): string {
    return removeProjectIdIfPresent(path.split(/[?#]/)[0]).replace(/\/+$/, '') || '/'
}

function firstSegment(pathname: string): string {
    return pathname.split('/')[1] ?? ''
}

function isAppStorePath(path: string): boolean {
    const pathname = pathnameOf(path)
    return pathname === urls.osAppStore() || pathname.startsWith(`${urls.osAppStore()}/`)
}

/**
 * The app a window path belongs to. An app claims every page under its link, and the longest link
 * wins. Several apps start on a sub-page (Session replay opens `/replay/home`), so a page that no link
 * covers goes to the only app that shares its top-level segment. When several apps share it, the
 * page belongs to none of them, because a guess would show another app's icon.
 */
export function osAppForPath(path: string, apps: OsApp[]): OsApp | null {
    const pathname = pathnameOf(path)
    let best: OsApp | null = null
    let bestScore = 0
    let tied = false
    for (const app of apps) {
        const href = pathnameOf(app.href)
        const score =
            pathname === href || pathname.startsWith(`${href}/`)
                ? 2 + href.length
                : firstSegment(pathname) === firstSegment(href)
                  ? 1
                  : 0
        if (score > bestScore) {
            best = app
            bestScore = score
            tied = false
        } else if (score > 0 && score === bestScore && app.key !== best?.key) {
            tied = true
        }
    }
    return tied ? null : best
}

/**
 * What the dock shows: the App Store, then one item per open window in the order the windows opened.
 * The top App Store window belongs to the App Store item, so it is not listed twice.
 */
export function osDockItems(windows: OsWindowState[], focusedWindowId: string | null, apps: OsApp[]): OsDockItems {
    const storeWindow = windows
        .filter((w) => isAppStorePath(w.path))
        .reduce<OsWindowState | null>((top, w) => (!top || w.zIndex > top.zIndex ? w : top), null)
    const stateOf = (w: OsWindowState): OsDockWindowState => ({
        focused: w.id === focusedWindowId,
        minimized: w.minimized,
    })

    return {
        store: storeWindow
            ? { windowId: storeWindow.id, ...stateOf(storeWindow) }
            : { windowId: null, focused: false, minimized: false },
        windows: windows
            .filter((w) => w !== storeWindow)
            .map((w) => ({ windowId: w.id, title: w.title, app: osAppForPath(w.path, apps), ...stateOf(w) })),
    }
}

export function osDockClickAction({ focused, minimized }: OsDockWindowState): OsDockClickAction {
    if (minimized) {
        return 'restore'
    }
    return focused ? 'minimize' : 'focus'
}
