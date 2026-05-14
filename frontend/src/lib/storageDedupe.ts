/**
 * Wraps `Storage.prototype.setItem` and `removeItem` so that calls on
 * `localStorage` and `sessionStorage` skip redundant writes — `setItem(k, v)`
 * becomes a no-op when the current stored value already equals `v`, and
 * `removeItem(k)` becomes a no-op when the key isn't present.
 *
 * Why: every `setItem` in Chromium broadcasts a `storage` event to every
 * other renderer in the same origin, and the receiver-side native IPC
 * memory accumulates over hours/days (see Chromium issue 351244335).
 * `posthog-js` writes its Persistence object on every internal mutation
 * (~4 writes/min on an idle tab in our reproducer), and most of those
 * writes serialize to a byte-identical payload. Deduplicating at this
 * layer suppresses the redundant broadcasts.
 *
 * Comparison reads the current value directly via the original `getItem`
 * each call. No shadow cache — so cross-tab writes, `storage.clear()`,
 * and any other out-of-band mutation can never cause a stale-cache skip.
 *
 * This is a defensive wrapper, not a behavior change. `setItem` with an
 * unchanged value is semantically a no-op for any reader that compares
 * before reading. If something downstream genuinely relied on the
 * `storage` event firing for same-value writes (cross-document), set
 * `sessionStorage.setItem('__ph_disable_storage_dedupe', '1')` before
 * the page loads to bypass the wrapper and report it.
 */

interface StorageDedupeMetrics {
    localSetSkipped: number
    localSetPassed: number
    localRemoveSkipped: number
    localRemovePassed: number
    sessionSetSkipped: number
    sessionSetPassed: number
    sessionRemoveSkipped: number
    sessionRemovePassed: number
    installedAt: number
}

declare global {
    interface Window {
        __phStorageDedupe?: StorageDedupeMetrics
    }
}

let installed = false

export function installStorageDedupe(): void {
    if (installed || typeof window === 'undefined' || typeof Storage === 'undefined') {
        return
    }
    try {
        if (window.sessionStorage?.getItem('__ph_disable_storage_dedupe') === '1') {
            return
        }
    } catch {
        return
    }
    installed = true

    const metrics: StorageDedupeMetrics = {
        localSetSkipped: 0,
        localSetPassed: 0,
        localRemoveSkipped: 0,
        localRemovePassed: 0,
        sessionSetSkipped: 0,
        sessionSetPassed: 0,
        sessionRemoveSkipped: 0,
        sessionRemovePassed: 0,
        installedAt: Date.now(),
    }
    window.__phStorageDedupe = metrics

    const origSet = Storage.prototype.setItem
    const origGet = Storage.prototype.getItem
    const origRemove = Storage.prototype.removeItem

    const kindOf = (storage: Storage): 'local' | 'session' | null => {
        if (storage === window.localStorage) {
            return 'local'
        }
        if (storage === window.sessionStorage) {
            return 'session'
        }
        return null
    }

    Storage.prototype.setItem = function (key: string, value: string): void {
        const kind = kindOf(this)
        if (kind && origGet.call(this, key) === value) {
            metrics[`${kind}SetSkipped`] += 1
            return
        }
        if (kind) {
            metrics[`${kind}SetPassed`] += 1
        }
        origSet.call(this, key, value)
    }

    Storage.prototype.removeItem = function (key: string): void {
        const kind = kindOf(this)
        if (kind && origGet.call(this, key) === null) {
            metrics[`${kind}RemoveSkipped`] += 1
            return
        }
        if (kind) {
            metrics[`${kind}RemovePassed`] += 1
        }
        origRemove.call(this, key)
    }
}
