import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import type { OsApp } from '../store/osAppCatalog'
import type { OsWindowState } from '../windows/osWindowsLogic'

/** The key of the App Store item. Store app keys are product tree paths, so they never take this value. */
export const OS_DOCK_STORE_KEY = 'app-store'

export interface OsDockItem {
    /** The app key, `OS_DOCK_STORE_KEY`, or `window:<id>` for a window no app claims. */
    key: string
    /** The app, for its icon and link. Null for the App Store and for a window no app claims. */
    app: OsApp | null
    /** The app name, or the window title for a window no app claims. */
    title: string
    /** The app's open windows, in the order they opened. */
    windowIds: string[]
    pinned: boolean
    focused: boolean
    /** The app has windows, and every one of them is minimized. */
    minimized: boolean
    someMinimized: boolean
}

export interface OsDockItems {
    store: OsDockItem
    apps: OsDockItem[]
}

export type OsDockClick = { action: 'open' } | { action: 'restore' | 'focus' | 'minimize'; windowId: string }

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
 * covers goes to the app that shares its top-level segment. When several apps share it, the page stays
 * with `previousKey`, the app the window showed before, if that app is one of them. Otherwise the page
 * belongs to none of them, because a guess would show another app's icon.
 */
export function osAppForPath(path: string, apps: OsApp[], previousKey?: string): OsApp | null {
    const pathname = pathnameOf(path)
    let best: OsApp[] = []
    let bestScore = 0
    for (const app of apps) {
        const href = pathnameOf(app.href)
        const score =
            pathname === href || pathname.startsWith(`${href}/`)
                ? 2 + href.length
                : firstSegment(pathname) === firstSegment(href)
                  ? 1
                  : 0
        if (score > bestScore) {
            best = [app]
            bestScore = score
        } else if (score > 0 && score === bestScore && !best.some((known) => known.key === app.key)) {
            best.push(app)
        }
    }
    if (best.length === 1) {
        return best[0]
    }
    return best.find((app) => app.key === previousKey) ?? null
}

/**
 * What the dock shows: the App Store, then the pinned apps in the order they were pinned, then the other
 * open apps in the order their first window opened. The windows of one app share one item, and a window
 * moves to another item when it navigates to another app. `previousAppKeys` maps a window id to the app it
 * showed before, for pages that several apps could claim. `claims` adds the pages each app lists in its menu
 * (`osAppClaims`). A window no app claims gets an item of its own.
 * A pin that no known app matches stays stored but is not shown, because the app list loads after the dock.
 */
export function osDockItems(
    windows: OsWindowState[],
    focusedWindowId: string | null,
    apps: OsApp[],
    pinnedKeys: string[],
    previousAppKeys: Record<string, string> = {},
    claims: OsApp[] = apps
): OsDockItems {
    const appsByKey = new Map(apps.map((app) => [app.key, app]))
    const items = new Map<string, OsDockItem>()
    const minimizedCount = new Map<string, number>()
    const itemFor = (key: string, app: OsApp | null, title: string, pinned: boolean): OsDockItem => {
        let item = items.get(key)
        if (!item) {
            item = { key, app, title, windowIds: [], pinned, focused: false, minimized: false, someMinimized: false }
            items.set(key, item)
        }
        return item
    }

    const store = itemFor(OS_DOCK_STORE_KEY, null, 'App Store', false)
    for (const key of pinnedKeys) {
        const app = appsByKey.get(key)
        if (app) {
            itemFor(key, app, app.name, true)
        }
    }
    for (const w of windows) {
        const owner = isAppStorePath(w.path) ? null : osAppForPath(w.path, claims, previousAppKeys[w.id])
        const app = owner ? (appsByKey.get(owner.key) ?? owner) : null
        const item = isAppStorePath(w.path)
            ? store
            : app
              ? itemFor(app.key, app, app.name, false)
              : itemFor(`window:${w.id}`, null, w.title, false)
        item.windowIds.push(w.id)
        item.focused ||= w.id === focusedWindowId
        if (w.minimized) {
            minimizedCount.set(item.key, (minimizedCount.get(item.key) ?? 0) + 1)
        }
    }
    for (const item of items.values()) {
        const minimized = minimizedCount.get(item.key) ?? 0
        item.minimized = item.windowIds.length > 0 && minimized === item.windowIds.length
        item.someMinimized = minimized > 0
    }

    return {
        store,
        apps: [...items.values()].filter((item) => item !== store && (item.pinned || item.windowIds.length > 0)),
    }
}

export function osDockClick(item: OsDockItem, windows: OsWindowState[]): OsDockClick {
    const own = windows.filter((w) => item.windowIds.includes(w.id)).sort((a, b) => b.zIndex - a.zIndex)
    const top = own.find((w) => !w.minimized)
    if (!own.length) {
        return { action: 'open' }
    }
    if (!top) {
        return { action: 'restore', windowId: own[0].id }
    }
    return { action: item.focused ? 'minimize' : 'focus', windowId: top.id }
}
