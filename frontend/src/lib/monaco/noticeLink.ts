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
    if (!url || !monaco || !isHttpsUrl(url)) {
        return undefined
    }
    // Uri.parse throws on surrounding whitespace.
    // Monaco gets the trimmed value that isHttpsUrl checked.
    return { value: 'Learn more', target: monaco.Uri.parse(url.trim()) }
}
