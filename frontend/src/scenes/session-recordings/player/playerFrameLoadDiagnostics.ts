export interface PlayerFrameLoadDiagnostics {
    frameDocumentReadable: boolean
    frameUrlPath: string | null
    frameDocumentTitle: string | null
    frameContentType: string | null
    frameReadyState: DocumentReadyState | null
    frameResponseStatus: number | null
    browserOnline: boolean
    pageVisibility: DocumentVisibilityState
    documentHasFocus: boolean
    frameMountHasFocus: boolean | null
    frameMountUserActivationActive: boolean | null
    msSinceFrameMount: number | null
    msSincePageLoad: number
}

interface PlayerFrameMount {
    hasFocus: boolean
    userActivationActive: boolean | null
    at: number
}

const MAX_TITLE_LENGTH = 100

// A failure is reported up to 10s after its frame mounted, and a click's user activation expires sooner, so
// the state that may decide whether the frame loads is read when the frame mounts.
const frameMounts = new WeakMap<HTMLIFrameElement, PlayerFrameMount>()

export function recordPlayerFrameMount(iframe: HTMLIFrameElement | null): void {
    if (!iframe) {
        return
    }
    try {
        frameMounts.set(iframe, {
            hasFocus: document.hasFocus(),
            userActivationActive: navigator.userActivation?.isActive ?? null,
            at: performance.now(),
        })
    } catch {
        // A diagnostic must never stop the frame from loading.
    }
}

// Resource Timing records the frame's navigation in the embedding document. A navigation that never finished has
// no entry, and some browsers leave out `responseStatus`. jsdom has no `getEntriesByName`, and the retry runs after
// this, so a missing API must not throw here.
function responseStatus(src: string): number | null {
    const entry = performance.getEntriesByName?.(src).at(-1) as PerformanceResourceTiming | undefined
    return entry?.responseStatus ?? null
}

// Describes what the frame loaded in place of the shell document, so a report can tell a network
// error page, an HTTP error, and a redirect apart.
export function getPlayerFrameLoadDiagnostics(iframe: HTMLIFrameElement | null): Partial<PlayerFrameLoadDiagnostics> {
    // A browser error page or a redirect to another origin makes the frame cross-origin, which hides its document.
    const frameDocument = iframe?.contentDocument ?? null
    const mount = iframe ? frameMounts.get(iframe) : undefined
    try {
        return {
            frameDocumentReadable: frameDocument !== null,
            // The path alone, because a query string can carry a token. A document with no browsing
            // context has a null location.
            frameUrlPath: frameDocument?.location?.pathname ?? null,
            frameDocumentTitle: frameDocument ? frameDocument.title.slice(0, MAX_TITLE_LENGTH) : null,
            frameContentType: frameDocument?.contentType ?? null,
            frameReadyState: frameDocument?.readyState ?? null,
            frameResponseStatus: iframe ? responseStatus(iframe.src) : null,
            browserOnline: navigator.onLine,
            pageVisibility: document.visibilityState,
            documentHasFocus: document.hasFocus(),
            // A retry from the error card almost always loads, and the automatic retries almost never do.
            // The click gives the page focus and user activation, so the report records both to test that.
            frameMountHasFocus: mount?.hasFocus ?? null,
            frameMountUserActivationActive: mount?.userActivationActive ?? null,
            msSinceFrameMount: mount ? Math.round(performance.now() - mount.at) : null,
            msSincePageLoad: Math.round(performance.now()),
        }
    } catch {
        // The retry runs after this report, so a read that throws must not stop it.
        return { frameDocumentReadable: frameDocument !== null }
    }
}
