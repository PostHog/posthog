export interface PlayerFrameLoadDiagnostics {
    frameDocumentReadable: boolean
    frameUrlPath: string | null
    frameDocumentTitle: string | null
    frameContentType: string | null
    frameReadyState: DocumentReadyState | null
    frameResponseStatus: number | null
    browserOnline: boolean
    pageVisibility: DocumentVisibilityState
    msSincePageLoad: number
}

const MAX_TITLE_LENGTH = 100

// Resource Timing records the frame's navigation in the embedding document. A navigation that never finished has
// no entry, and some browsers leave out `responseStatus`. jsdom has no `getEntriesByName`, and the retry runs after
// this, so a missing API must not throw here.
function responseStatus(src: string): number | null {
    const entry = performance.getEntriesByName?.(src).at(-1) as PerformanceResourceTiming | undefined
    return entry?.responseStatus ?? null
}

// Describes what the frame loaded in place of the shell document, so a report can tell a network
// error page, an HTTP error, and a redirect apart.
export function getPlayerFrameLoadDiagnostics(iframe: HTMLIFrameElement | null): PlayerFrameLoadDiagnostics {
    // A browser error page or a redirect to another origin makes the frame cross-origin, which hides its document.
    const frameDocument = iframe?.contentDocument ?? null
    return {
        frameDocumentReadable: frameDocument !== null,
        // The path alone, because a query string can carry a token.
        frameUrlPath: frameDocument?.location.pathname ?? null,
        frameDocumentTitle: frameDocument ? frameDocument.title.slice(0, MAX_TITLE_LENGTH) : null,
        frameContentType: frameDocument?.contentType ?? null,
        frameReadyState: frameDocument?.readyState ?? null,
        frameResponseStatus: iframe ? responseStatus(iframe.src) : null,
        browserOnline: navigator.onLine,
        pageVisibility: document.visibilityState,
        msSincePageLoad: Math.round(performance.now()),
    }
}
