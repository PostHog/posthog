import { decodeHtmlEntitiesInHref } from '../email-tracking.service'

export type UtmTags = {
    utm_source: string
    utm_medium: string
    utm_campaign: string
}

const ANCHOR_HREF_REGEX = /(<a\b[^>]*?\bhref\s*=\s*)(?:"([^"]*)"|'([^']*)')/gi

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
export const addUtmTagsToUrl = (url: string, tags: UtmTags, siteHost: string | null): string | null => {
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

export const addUtmTagsToEmail = (html: string, tags: UtmTags, siteUrl: string): string => {
    const siteHost = hostOf(siteUrl)
    return html.replace(ANCHOR_HREF_REGEX, (match, prefix: string, doubleQuoted?: string, singleQuoted?: string) => {
        const quote = doubleQuoted !== undefined ? '"' : "'"
        const tagged = addUtmTagsToUrl(decodeHtmlEntitiesInHref(doubleQuoted ?? singleQuoted ?? ''), tags, siteHost)
        if (tagged === null) {
            return match
        }
        const encoded = tagged
            .replace(/&/g, '&amp;')
            .replace(quote === '"' ? /"/g : /'/g, quote === '"' ? '&quot;' : '&#39;')
        return `${prefix}${quote}${encoded}${quote}`
    })
}
