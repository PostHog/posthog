/**
 * `copied` — the text is on the clipboard, by any route.
 * `unavailable` — the browser exposes no Clipboard API, which is the plain-HTTP case the toolbar runs in.
 * `failed` — a write was attempted and did not land.
 */
export type ClipboardWriteOutcome = 'copied' | 'unavailable' | 'failed'

/**
 * Writes to the clipboard with no user-facing feedback, so callers that report through a toast can use it
 * without depending on the toast module.
 */
export async function writeToClipboard(value: string, html?: string): Promise<ClipboardWriteOutcome> {
    if (!navigator.clipboard) {
        return writeThroughSelection(value) ? 'copied' : 'unavailable'
    }

    // Writing both formats lets a paste target that understands HTML keep the formatting, while
    // plain-text targets still receive `value`. Browser support for `text/html` in a ClipboardItem
    // is not universal, so a failure here falls through to the plain-text write below rather than
    // failing the copy.
    if (html && typeof ClipboardItem !== 'undefined' && navigator.clipboard.write) {
        try {
            await navigator.clipboard.write([
                new ClipboardItem({
                    'text/html': new Blob([html], { type: 'text/html' }),
                    'text/plain': new Blob([value], { type: 'text/plain' }),
                }),
            ])
            return 'copied'
        } catch {
            // Fall through to the plain-text paths.
        }
    }

    try {
        await navigator.clipboard.writeText(value)
        return 'copied'
    } catch {
        return writeThroughSelection(value) ? 'copied' : 'failed'
    }
}

/** The pre-Clipboard-API route. Still the only one that works over plain HTTP and in some embedded contexts. */
function writeThroughSelection(value: string): boolean {
    try {
        const textArea = document.createElement('textarea')
        textArea.value = value
        document.body.appendChild(textArea)
        textArea.select()
        document.execCommand('copy')
        document.body.removeChild(textArea)
        return true
    } catch {
        return false
    }
}
