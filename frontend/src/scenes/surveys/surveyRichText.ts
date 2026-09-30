import type { SupportEditorFormat } from 'products/conversations/frontend/components/Editor'

export const SURVEY_RICH_TEXT_FORMATS: SupportEditorFormat[] = ['bold', 'italic', 'underline', 'strike', 'link']

// The tags and attributes that SURVEY_RICH_TEXT_FORMATS output, after normalizeRichTextHtml. The editor drops all others.
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

export function htmlToPlainText(html: string): string {
    const doc = new DOMParser().parseFromString(html, 'text/html')
    doc.body.querySelectorAll('br').forEach((br) => br.replaceWith('\n'))
    const paragraphs = Array.from(doc.body.children).filter((child) => child.tagName === 'P')
    if (paragraphs.length > 0 && paragraphs.length === doc.body.children.length) {
        return paragraphs.map((p) => p.textContent ?? '').join('\n')
    }
    return doc.body.textContent ?? ''
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
 * The editor adds CSS classes for its own styles. The survey does not have these styles, so they are removed.
 */
export function normalizeRichTextHtml(html: string): string {
    const doc = new DOMParser().parseFromString(html, 'text/html')
    doc.body.querySelectorAll('[class]').forEach((element) => element.removeAttribute('class'))
    const blocks = doc.body.children
    if (blocks.length === 1 && blocks[0].tagName === 'P') {
        return blocks[0].innerHTML.trim() ? blocks[0].innerHTML : ''
    }
    return doc.body.innerHTML
}
