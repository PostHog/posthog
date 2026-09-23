import { osLinkTarget } from './osFrameRouting'

// Kept free of logic and scene imports, because app-wide helpers such as `newInternalTab` import it.
let windowOpener: ((path: string) => void) | null = null

/**
 * Registers how this page opens an app path in a new OS window. The framed app asks the OS page, and the
 * OS page opens the window itself. Pass null when the bridge unmounts.
 */
export function setOsWindowOpener(opener: ((path: string) => void) | null): void {
    windowOpener = opener
}

/**
 * Opens an app path in a new OS window when this page belongs to the OS. Returns false when the caller must
 * open it the regular way: without the OS, or for a page that cannot load in a window.
 */
export function openInOsWindow(href: string): boolean {
    if (!windowOpener) {
        return false
    }
    const target = osLinkTarget(
        {
            href,
            target: '_blank',
            download: false,
            button: 0,
            metaKey: false,
            ctrlKey: false,
            shiftKey: false,
            altKey: false,
        },
        window.location.href
    )
    if (target?.kind !== 'new-window') {
        return false
    }
    windowOpener(target.path)
    return true
}
