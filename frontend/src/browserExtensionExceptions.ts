import { BeforeSendFn } from 'posthog-js'

interface RawStackFrame {
    filename?: string
    function?: string
    lineno?: number
}

/**
 * Browser extensions (crypto wallets, reader modes) inject an inline script into every page they
 * open. When that script throws, its only stack frame is `global code` at line 1 of the document
 * URL, and posthog-js marks the frame `in_app` — so error tracking reads it as a first-party app
 * error. The URL is part of the fingerprint, so each scene a visitor opens makes another issue for
 * the same fault, and none of them is ours to fix.
 *
 * The app always loads its own code from separate script files, so a single line 1 frame whose
 * filename is the document URL is always injected script.
 */
export const dropBrowserExtensionExceptions: BeforeSendFn = (event) => {
    if (event?.event !== '$exception') {
        return event
    }
    const exceptionList = event.properties?.$exception_list
    if (!Array.isArray(exceptionList)) {
        return event
    }
    // The frame filename holds the document URL without its query string or hash.
    const documentUrl = window.location.origin + window.location.pathname
    const isInjectedInlineScript = exceptionList.some((exception) => {
        const frames: RawStackFrame[] = exception?.stacktrace?.frames ?? []
        const frame = frames.length === 1 ? frames[0] : undefined
        return frame?.function === 'global code' && frame.lineno === 1 && frame.filename === documentUrl
    })
    return isInjectedInlineScript ? null : event
}
