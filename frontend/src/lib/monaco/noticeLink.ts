import type { Monaco } from '@monaco-editor/react'
import type { editor } from 'monaco-editor'

import { isHttpsUrl } from 'lib/utils/url'

/**
 * The "Learn more" link that a notice's url adds to its marker hover, or undefined for no link.
 *
 * Monaco renders the marker message as plain text.
 * The `code` field is the only marker field that Monaco renders as a link.
 * Monaco runs a `command:` link as an editor command.
 * Monaco assigns any other non-http link to window.location.
 * Only an https URL becomes a link for these reasons.
 */
export function noticeLink(
    url: string | null | undefined,
    monaco: Pick<Monaco, 'Uri'> | null | undefined
): editor.IMarkerData['code'] {
    const trimmed = url?.trim()
    if (!trimmed || !monaco || !isHttpsUrl(trimmed)) {
        return undefined
    }
    try {
        return { value: 'Learn more', target: monaco.Uri.parse(trimmed) }
    } catch {
        // Uri.parse rejects some URLs that isHttpsUrl accepts, such as `https:////x`.
        // An exception here would stop every marker for the query.
        // The catch drops only the link.
        return undefined
    }
}
