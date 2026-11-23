import { Parser } from 'htmlparser2'

const SKIPPED_ELEMENTS = new Set(['head', 'script', 'style', 'title', 'noscript', 'template'])
const LINE_BREAK_ELEMENTS = new Set(['div', 'tr', 'table', 'section', 'article', 'header', 'footer', 'center'])
const PARAGRAPH_ELEMENTS = new Set(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'blockquote', 'hr', 'pre'])
const CELL_ELEMENTS = new Set(['td', 'th'])

const HIDDEN_STYLE = /display\s*:\s*none/i
const INVISIBLE_CHARACTERS = /[\u00ad\u034f\u200b\u2060\ufeff]/g
const WHITESPACE = /\s+/g
const VISIBLE_CHARACTER = /[^\s\u200c\u200d]/

const isSkipped = (name: string, attributes: Record<string, string>): boolean =>
    SKIPPED_ELEMENTS.has(name) || HIDDEN_STYLE.test(attributes.style ?? '')

const breakFor = (name: string, opening: boolean): string => {
    if (name === 'li') {
        return opening ? '\n- ' : ''
    }
    if (name === 'br') {
        return opening ? '\n' : ''
    }
    if (PARAGRAPH_ELEMENTS.has(name)) {
        return '\n\n'
    }
    if (LINE_BREAK_ELEMENTS.has(name)) {
        return '\n'
    }
    return CELL_ELEMENTS.has(name) ? ' ' : ''
}

const linkTarget = (href: string | undefined): string | null => {
    const target = href?.trim() ?? ''
    return target && !target.startsWith('#') && !/^javascript:/i.test(target) ? target : null
}

const linkSuffix = (label: string, target: string): string => {
    const shownTarget = target.replace(/^mailto:/i, '')
    if (!label) {
        return shownTarget
    }
    return label === shownTarget || label === target ? '' : ` (${shownTarget})`
}

const tidyLines = (text: string): string =>
    text
        .split('\n')
        .map((line) => line.replace(/ {2,}/g, ' ').trim())
        .join('\n')
        .replace(/\n{3,}/g, '\n\n')
        .trim()

type OpenLink = { target: string; labelStart: number }

export const plainTextFromHtml = (html: string): string => {
    const out: string[] = []
    let depth = 0
    let preDepth = 0
    let skippedAt: number | null = null
    let link: OpenLink | null = null

    const parser = new Parser({
        onopentag(name, attributes) {
            depth++
            if (skippedAt !== null) {
                return
            }
            if (isSkipped(name, attributes)) {
                skippedAt = depth
                return
            }
            if (name === 'pre') {
                preDepth++
            }
            if (name === 'a') {
                const target = linkTarget(attributes.href)
                link = target ? { target, labelStart: out.length } : null
            }
            out.push(breakFor(name, true))
        },
        ontext(text) {
            if (skippedAt === null) {
                const visible = text.replace(INVISIBLE_CHARACTERS, '')
                out.push(preDepth > 0 ? visible.replace(/\r\n?/g, '\n') : visible.replace(WHITESPACE, ' '))
            }
        },
        onclosetag(name) {
            if (skippedAt === null) {
                if (name === 'a' && link) {
                    out.push(linkSuffix(tidyLines(out.slice(link.labelStart).join('')), link.target))
                    link = null
                }
                if (name === 'pre') {
                    preDepth--
                }
                out.push(breakFor(name, false))
            } else if (skippedAt === depth) {
                skippedAt = null
            }
            depth--
        },
    })
    parser.write(html)
    parser.end()

    const text = tidyLines(out.join(''))
    return VISIBLE_CHARACTER.test(text) ? text : ''
}
