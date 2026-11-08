import { decodeHtmlEntitiesInHref } from '../email-tracking.service'
import { escapeHtml } from './escape-html'
import type { UtmTags } from './utm'

// The previous link scanner, unchanged. Teams outside CDP_EMAIL_UTM_LINK_SCANNER_TEAMS still run it, so the
// scanner in utm.ts can roll out team by team. Delete this file once every team runs the scanner in utm.ts.

// One attribute per match, so `href` and `data-ph-no-utm` count only as attribute names, never as text
// inside another attribute's value or as part of a longer name like `data-href`.
const ATTRIBUTE_REGEX = /\s([^\s"'<>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g

const hostOf = (url: string): string | null => {
    try {
        return new URL(url).host
    } catch {
        return null
    }
}

/**
 * Appends each UTM tag the link does not already carry. Returns null when the link stays as is:
 * not an absolute http(s) URL, a link to PostHog itself (unsubscribe and preference pages), an
 * unrendered template tag, or a link that already has every tag.
 */
const addUtmTagsToUrl = (url: string, tags: UtmTags, siteHost: string | null): string | null => {
    if (url.includes('{{') || url.includes('{%')) {
        return null
    }
    let parsed: URL
    try {
        parsed = new URL(url)
    } catch {
        return null
    }
    if ((parsed.protocol !== 'http:' && parsed.protocol !== 'https:') || parsed.host === siteHost) {
        return null
    }
    const missing = Object.entries(tags).filter(([key, value]) => value && !parsed.searchParams.has(key))
    if (missing.length === 0) {
        return null
    }
    // Append to the original string rather than serializing the URL, so the rest of the link stays byte for byte.
    const hashIndex = url.indexOf('#')
    const base = hashIndex === -1 ? url : url.slice(0, hashIndex)
    const hash = hashIndex === -1 ? '' : url.slice(hashIndex)
    const separator = !base.includes('?') ? '?' : base.endsWith('?') || base.endsWith('&') ? '' : '&'
    const query = missing.map(([key, value]) => `${key}=${encodeURIComponent(value)}`).join('&')
    return `${base}${separator}${query}${hash}`
}

/** Index of the `>` that closes the tag opened before `from`, skipping quoted values, or -1 if it never closes. */
const findTagEnd = (html: string, from: number): number => {
    let quote: string | null = null
    for (let i = from; i < html.length; i++) {
        const char = html[i]
        if (quote) {
            if (char === quote) {
                quote = null
            }
        } else if (char === '"' || char === "'") {
            quote = char
        } else if (char === '>') {
            return i
        }
    }
    return -1
}

const tagAnchor = (anchor: string, tags: UtmTags, siteHost: string | null): string => {
    const attributes = [...anchor.matchAll(ATTRIBUTE_REGEX)]
    if (attributes.some((attribute) => attribute[1].toLowerCase() === 'data-ph-no-utm')) {
        return anchor
    }
    const href = attributes.find((attribute) => attribute[1].toLowerCase() === 'href')
    const value = href ? (href[2] ?? href[3]) : undefined
    if (!href || value === undefined) {
        return anchor
    }
    const tagged = addUtmTagsToUrl(decodeHtmlEntitiesInHref(value), tags, siteHost)
    if (tagged === null) {
        return anchor
    }
    const quote = href[2] !== undefined ? '"' : "'"
    const encoded = escapeHtml(tagged)
    const start = href.index! + href[0].indexOf('=')
    return anchor.slice(0, start) + `=${quote}${encoded}${quote}` + anchor.slice(href.index! + href[0].length)
}

// One forward pass rather than a regex, so a body full of unclosed `<a` tags costs linear time instead
// of rescanning the rest of the email for each one and stalling the worker.
export const addUtmTagsToEmailLegacy = (html: string, tags: UtmTags, siteUrl: string): string => {
    const siteHost = hostOf(siteUrl)
    const lower = html.toLowerCase()
    let output = ''
    let cursor = 0
    while (cursor < html.length) {
        const start = lower.indexOf('<a', cursor)
        if (start === -1) {
            break
        }
        const after = lower[start + 2]
        if (after !== undefined && !/[\s>/]/.test(after)) {
            // `<abbr>`, `<area>` and other tags that only start with "a".
            output += html.slice(cursor, start + 2)
            cursor = start + 2
            continue
        }
        const end = findTagEnd(html, start + 2)
        if (end === -1) {
            // The tag never closes, so it is not a link, and the rest of the email is left as is.
            break
        }
        output += html.slice(cursor, start) + tagAnchor(html.slice(start, end + 1), tags, siteHost)
        cursor = end + 1
    }
    return output + html.slice(cursor)
}
