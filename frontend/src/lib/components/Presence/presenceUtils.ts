import { uuid } from 'lib/utils/dom'

import type { PresenceViewerApi } from '~/generated/core/api.schemas'

/** How often each tab tells the server it's still here. */
export const PRESENCE_HEARTBEAT_INTERVAL_MS = 10_000
/** How often we re-check locally, so avatars fade even when the network stalls. */
export const PRESENCE_PRUNE_INTERVAL_MS = 5_000
/** A viewer we haven't heard about for this long is treated as gone. Matches the server's TTL. */
export const PRESENCE_VIEWER_TTL_MS = 30_000
/** How long "replying..." sticks around after the last keystroke. */
export const PRESENCE_COMPOSING_TIMEOUT_MS = 8_000

const CLIENT_ID_SESSION_STORAGE_KEY = 'ph-presence-client-id'

/**
 * One id per browser tab, stable for the life of the tab. Two tabs are two clients, which is what
 * lets the UI collapse them back into a single viewer.
 */
export function getPresenceClientId(): string {
    const nextClientId = uuid()
    if (typeof window === 'undefined') {
        return nextClientId
    }

    try {
        const storedClientId = window.sessionStorage.getItem(CLIENT_ID_SESSION_STORAGE_KEY)
        if (storedClientId) {
            return storedClientId
        }
        window.sessionStorage.setItem(CLIENT_ID_SESSION_STORAGE_KEY, nextClientId)
    } catch {
        // Storage can be unavailable in private or embedded contexts. Presence is best effort.
    }

    return nextClientId
}

export function pruneStaleViewers(
    viewers: PresenceViewerApi[],
    now: number,
    ttlMs: number = PRESENCE_VIEWER_TTL_MS
): PresenceViewerApi[] {
    return viewers.filter((viewer) => now - new Date(viewer.last_seen_at).getTime() < ttlMs)
}

/**
 * Collapse a user's tabs into one viewer. Freshest wins, except that composing beats viewing: a
 * user with a stale composing tab and a fresh idle one is still writing something.
 */
export function dedupeViewersByUser(viewers: PresenceViewerApi[]): PresenceViewerApi[] {
    const byUser = new Map<number, PresenceViewerApi>()

    for (const viewer of viewers) {
        const existing = byUser.get(viewer.user.id)
        if (!existing || wins(viewer, existing)) {
            byUser.set(viewer.user.id, viewer)
        }
    }

    return [...byUser.values()].sort((a, b) => {
        if (isComposing(a) !== isComposing(b)) {
            return isComposing(a) ? -1 : 1
        }
        return presenceName(a).localeCompare(presenceName(b))
    })
}

export function presenceName(viewer: PresenceViewerApi): string {
    return viewer.user.first_name || viewer.user.email
}

function isComposing(viewer: PresenceViewerApi): boolean {
    return viewer.activity === 'composing'
}

function wins(candidate: PresenceViewerApi, incumbent: PresenceViewerApi): boolean {
    if (isComposing(candidate) !== isComposing(incumbent)) {
        return isComposing(candidate)
    }
    return new Date(candidate.last_seen_at) > new Date(incumbent.last_seen_at)
}

/**
 * Describe who's here, in one line. `noun` names the thing being looked at, e.g. "this ticket".
 * Returns null when there's nobody else to mention.
 */
export function describePresence(viewers: PresenceViewerApi[], noun: string): string | null {
    if (!viewers.length) {
        return null
    }

    const composing = viewers.filter(isComposing).map(presenceName)
    const watching = viewers.filter((viewer) => !isComposing(viewer)).map(presenceName)

    if (!composing.length) {
        return `${joinNames(watching)} ${watching.length === 1 ? 'is' : 'are'} viewing ${noun}`
    }

    const replying = `${joinNames(composing)} ${composing.length === 1 ? 'is' : 'are'} replying...`
    if (!watching.length) {
        return replying
    }
    if (watching.length === 1) {
        return `${replying}, ${watching[0]} is viewing`
    }
    return `${replying}, ${watching.length} others are viewing`
}

function joinNames(names: string[]): string {
    if (names.length <= 2) {
        return names.join(' and ')
    }
    return `${names[0]}, ${names[1]} and ${names.length - 2} ${names.length === 3 ? 'other' : 'others'}`
}
