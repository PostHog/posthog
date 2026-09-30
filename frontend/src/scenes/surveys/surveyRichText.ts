import StarterKit from '@tiptap/starter-kit'

import { LinkExtension } from 'lib/components/RichContentEditor/LinkExtension'

export const SURVEY_RICH_TEXT_EXTENSIONS = [
    StarterKit.configure({
        heading: false,
        code: false,
        codeBlock: false,
        blockquote: false,
        horizontalRule: false,
        bulletList: false,
        orderedList: false,
        listItem: false,
        listKeymap: false,
        link: false,
    }),
    LinkExtension.configure({ openOnClick: false }),
]

// The tags and attributes that SURVEY_RICH_TEXT_EXTENSIONS output. The editor drops all others.
const RICH_TEXT_TAGS = new Set(['P', 'BR', 'STRONG', 'B', 'EM', 'I', 'U', 'S', 'A'])
const RICH_TEXT_LINK_ATTRIBUTES = new Set(['href', 'target', 'rel'])

function escapeHtml(text: string): string {
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

export function plainTextToHtml(text: string): string {
    if (!text.trim()) {
        return ''
    }
    const lines = text.split('\n')
    if (lines.length === 1) {
        return escapeHtml(text)
    }
    return lines.map((line) => `<p>${escapeHtml(line)}</p>`).join('')
}

export function isRichTextCompatibleHtml(html: string): boolean {
    const doc = new DOMParser().parseFromString(html, 'text/html')
    return Array.from(doc.body.querySelectorAll('*')).every((element) => {
        if (!RICH_TEXT_TAGS.has(element.tagName)) {
            return false
        }
        return element
            .getAttributeNames()
            .every((name) => element.tagName === 'A' && RICH_TEXT_LINK_ATTRIBUTES.has(name))
    })
}

/**
 * The SDKs render the description inside their own <p>, so a single paragraph is saved without its wrapper.
 * An empty editor gives "<p></p>", which is saved as an empty string.
 */
export function normalizeRichTextHtml(html: string): string {
    const doc = new DOMParser().parseFromString(html, 'text/html')
    const blocks = doc.body.children
    if (blocks.length === 1 && blocks[0].tagName === 'P') {
        return blocks[0].innerHTML.trim() ? blocks[0].innerHTML : ''
    }
    return html
}
