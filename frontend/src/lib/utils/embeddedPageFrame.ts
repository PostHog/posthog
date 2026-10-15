/** The name of a frame that shows an app page inside another app page, such as a cited object in a task. */
export const EMBEDDED_PAGE_FRAME_NAME = 'posthog-embedded-page'

/**
 * True when this document is an app page inside an embedded page frame, so it renders without the app's
 * navigation. The frame name stays when the page navigates inside the frame. The origin check makes sure
 * only the app itself can turn the mode on.
 */
export function isEmbeddedPageFrame(): boolean {
    if (typeof window === 'undefined' || window.name !== EMBEDDED_PAGE_FRAME_NAME || window.parent === window) {
        return false
    }
    try {
        return window.parent.location.origin === window.location.origin
    } catch {
        // A cross-origin parent throws on any read of its location.
        return false
    }
}
