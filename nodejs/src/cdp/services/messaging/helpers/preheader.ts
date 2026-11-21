// `[^<>]*` so a match attempt at an unterminated `<body ` stops at the next tag instead of the end.
const BODY_OPEN_TAG = /<body\b[^<>]*>/i
const OPEN_TAG = /<([a-z][a-z0-9]*)\b[^<>]*>/gi
const CLOSE_TAG = /<\/[a-z][a-z0-9]*\s*>/gi
const STYLE_CLOSE = /<\/style/gi
const SCRIPT_CLOSE = /<\/script/gi
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

// Comment markup, including an Outlook-only `<!--[if mso]>` branch, never renders where the preview
// is read. An indexOf walk, because unclosed `<!--` makes a lazy regex rescan to the end for each one.
const stripComments = (html: string): string => {
    let start = html.indexOf('<!--')
    if (start === -1) {
        return html
    }
    let out = ''
    let pos = 0
    while (start !== -1) {
        out += html.slice(pos, start)
        const end = html.indexOf('-->', start + 4)
        if (end === -1) {
            // An unclosed comment hides everything after it.
            return out
        }
        pos = end + 3
        start = html.indexOf('<!--', pos)
    }
    return out + html.slice(pos)
}

// The editor can bake the preview into the template as a hidden element already, so a second copy
// from the step would show twice. Only a hidden element before any other body text acts as the preview.
const hasHiddenPreheader = (html: string, preheader: string): boolean => {
    const wanted = visibleText(preheader).toLowerCase()
    const stripped = stripComments(html)
    const bodyOpen = BODY_OPEN_TAG.exec(stripped)
    const body = bodyOpen ? stripped.slice(bodyOpen.index + bodyOpen[0].length) : stripped
    let textFrom = 0
    for (const openTag of body.matchAll(OPEN_TAG)) {
        if (openTag.index < textFrom) {
            // A tag inside stylesheet or script contents we already skipped past.
            continue
        }
        if (visibleText(body.slice(textFrom, openTag.index).replace(CLOSE_TAG, '')) !== '') {
            return false
        }
        const contentStart = openTag.index + openTag[0].length
        textFrom = contentStart
        const tagName = openTag[1].toLowerCase()
        if (tagName === 'style' || tagName === 'script') {
            // Stylesheet and script contents never render, so they cannot be the preview. The regex
            // reports offsets in the original string; `toLowerCase()` could shift them (`İ` grows).
            const closeSearch = tagName === 'style' ? STYLE_CLOSE : SCRIPT_CLOSE
            closeSearch.lastIndex = contentStart
            const close = closeSearch.exec(body)
            if (!close) {
                return false
            }
            textFrom = close.index
            continue
        }
        if (!HIDDEN_STYLE.test(openTag[0])) {
            continue
        }
        // A matching element's content holds no markup, so its closing tag can only be the next tag.
        // Checking just that position keeps the scan linear instead of rescanning per hidden tag.
        const contentEnd = body.indexOf('<', contentStart)
        if (contentEnd === -1) {
            continue
        }
        const closeTag = `</${tagName}`
        if (body.slice(contentEnd, contentEnd + closeTag.length).toLowerCase() !== closeTag) {
            continue
        }
        if (visibleText(body.slice(contentStart, contentEnd)).toLowerCase() === wanted) {
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
