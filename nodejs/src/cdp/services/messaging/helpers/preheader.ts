const BODY_OPEN_TAG = /<body\b[^>]*>/i
const OPEN_TAG = /<([a-z][a-z0-9]*)\b[^<>]*>/gi
const HIDDEN_STYLE = /display\s*:\s*none/i
const ENTITY = /&(#x[0-9a-f]+|#\d+|[a-z]+);/gi
const NAMED_ENTITIES: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' }

const decodeEntity = (entity: string, body: string): string => {
    const key = body.toLowerCase()
    if (key.startsWith('#')) {
        const codePoint = key.startsWith('#x') ? parseInt(key.slice(2), 16) : parseInt(key.slice(1), 10)
        return codePoint > 0 && codePoint <= 0x10ffff ? String.fromCodePoint(codePoint) : entity
    }
    return NAMED_ENTITIES[key] ?? entity
}

const visibleText = (text: string): string =>
    text
        .replace(ENTITY, decodeEntity)
        .replace(/[\s ]+/g, ' ')
        .trim()

// The editor can bake the preview text into the template as a hidden element already, so adding the
// step's own copy as well makes inboxes show the preview twice.
const hasHiddenPreheader = (html: string, preheader: string): boolean => {
    const wanted = visibleText(preheader)
    let lowerCased: string | undefined
    for (const openTag of html.matchAll(OPEN_TAG)) {
        if (!HIDDEN_STYLE.test(openTag[0])) {
            continue
        }
        const contentStart = openTag.index + openTag[0].length
        lowerCased ??= html.toLowerCase()
        const contentEnd = lowerCased.indexOf(`</${openTag[1].toLowerCase()}`, contentStart)
        if (contentEnd === -1) {
            continue
        }
        const content = html.slice(contentStart, contentEnd)
        if (!content.includes('<') && visibleText(content) === wanted) {
            return true
        }
    }
    return false
}

export const maybeAddPreheaderToEmail = (html: string, preheader?: string): string => {
    if (!preheader || hasHiddenPreheader(html, preheader)) {
        return html
    }

    const preheaderHtml = `<span style="display:none !important;visibility:hidden;mso-hide:all;font-size:1px;color:#ffffff;line-height:1px;max-height:0px;max-width:0px;opacity:0;overflow:hidden;">${preheader}</span>`
    // Inboxes take the preview from the first text in the body, so the hidden text goes right after
    // the opening body tag. HTML without one, such as a fragment saved through the API, gets it first.
    const bodyOpen = BODY_OPEN_TAG.exec(html)
    if (!bodyOpen) {
        return preheaderHtml + html
    }
    const insertAt = bodyOpen.index + bodyOpen[0].length
    return html.slice(0, insertAt) + preheaderHtml + html.slice(insertAt)
}
