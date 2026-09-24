import { OS_FRAME_NAME_PREFIX, isOsFrame } from '../bridge/osFrame'

// pinned: message types cross frames, so an older frame and a newer OS page must still agree on them
const INSTALLED_CHANGED = 'posthog-os-store:installed-changed'
const OPEN_APP = 'posthog-os-store:open-app'
const PREVIEW_APP = 'posthog-os-store:preview-app'

/**
 * What the App Store window tells the OS page. The store runs in its own frame with its own copy of
 * the installed-apps list, so the page reloads its copy when the store changes it. An app to open or
 * preview is sent as a catalog key, never as a URL, so a frame can only ask for apps the OS already knows.
 */
export type OsStoreMessage =
    | { type: typeof INSTALLED_CHANGED }
    | { type: typeof OPEN_APP; key: string }
    | { type: typeof PREVIEW_APP; key: string }

export const osStoreInstalledChanged = (): OsStoreMessage => ({ type: INSTALLED_CHANGED })
export const osStoreOpenApp = (key: string): OsStoreMessage => ({ type: OPEN_APP, key })
export const osStorePreviewApp = (key: string): OsStoreMessage => ({ type: PREVIEW_APP, key })

/** Sends a message to the OS page. Does nothing outside an OS window. */
export function postToOs(message: OsStoreMessage, win: Window = window): boolean {
    if (!isOsFrame(win)) {
        return false
    }
    win.parent.postMessage(message, win.location.origin)
    return true
}

function isOwnOsFrame(source: MessageEventSource | null, win: Window): boolean {
    try {
        const frame = source as Window | null
        return !!frame && frame !== win && frame.parent === win && frame.name.startsWith(OS_FRAME_NAME_PREFIX)
    } catch {
        // A frame on another origin throws on `name`, and it is never one of our windows.
        return false
    }
}

/** The store message in `event`, or null when it did not come from one of this page's OS windows. */
export function readOsStoreMessage(event: MessageEvent, win: Window = window): OsStoreMessage | null {
    if (event.origin !== win.location.origin || !isOwnOsFrame(event.source, win)) {
        return null
    }
    const data = event.data as { type?: unknown; key?: unknown } | null
    if (data?.type === INSTALLED_CHANGED) {
        return osStoreInstalledChanged()
    }
    if (data?.type === OPEN_APP && typeof data.key === 'string') {
        return osStoreOpenApp(data.key)
    }
    if (data?.type === PREVIEW_APP && typeof data.key === 'string') {
        return osStorePreviewApp(data.key)
    }
    return null
}
