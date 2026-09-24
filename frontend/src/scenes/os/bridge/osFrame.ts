// pinned: every OS window frame carries this name prefix, and the framed app reads it to hide its chrome
export const OS_FRAME_NAME_PREFIX = 'posthog-os-window:'

export function osFrameName(windowId: string): string {
    return `${OS_FRAME_NAME_PREFIX}${windowId}`
}

// A frame keeps its name across navigations and reloads, so framed mode needs no query param or
// storage. posthog.com also frames the app, but without the prefix, so it keeps the regular layout.
export function isOsFrame(win: Window): boolean {
    return win.self !== win.top && win.name.startsWith(OS_FRAME_NAME_PREFIX)
}

// pinned: the OS page sets this attribute on a window frame while it previews an app that is not installed
export const OS_PREVIEW_FRAME_ATTRIBUTE = 'data-os-preview'

export function isOsPreviewFrame(win: Window): boolean {
    try {
        return isOsFrame(win) && !!win.frameElement?.hasAttribute(OS_PREVIEW_FRAME_ATTRIBUTE)
    } catch {
        return false
    }
}

export interface OsFrameLocation {
    pathname: string
    search: string
    hash: string
}

// A pathname such as `//example.com/x` or `/\example.com/x` is protocol-relative in a frame `src`,
// so using it as-is would load another site inside a PostHog window.
export function osFrameSrc({ pathname, search, hash }: OsFrameLocation, origin: string): string | null {
    const url = new URL(`${pathname}${search}${hash}`, origin)
    if (url.origin !== new URL(origin).origin) {
        return null
    }
    return `${url.pathname}${url.search}${url.hash}`
}
