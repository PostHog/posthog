import { HogFunctionInvocationGlobalsWithInputs } from '~/cdp/types'
import { LiquidRenderer } from '~/cdp/utils/liquid'

import { decodeHtmlEntitiesInHref } from '../email-tracking.service'

export type UtmTags = {
    utm_source: string
    utm_medium: string
    utm_campaign: string
    utm_content: string
}

const UTM_KEYS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content'] as const

const ANCHOR_TAG_REGEX = /<a\b[^>]*>/gi
const HREF_ATTR_REGEX = /(\bhref\s*=\s*)(?:"([^"]*)"|'([^']*)')/i
const UTM_OPT_OUT_REGEX = /\bdata-ph-no-utm\b/i

/**
 * Renders each custom value as Liquid with the recipient's data. A value that fails to render is
 * reported and left out, so one bad template keeps its default instead of failing the send.
 */
export const renderUtmOverrides = (
    raw: unknown,
    globals: HogFunctionInvocationGlobalsWithInputs,
    onError: (key: string, message: string) => void
): Record<string, string> => {
    const rendered: Record<string, string> = {}
    if (!raw || typeof raw !== 'object') {
        return rendered
    }
    for (const key of UTM_KEYS) {
        const value = (raw as Record<string, unknown>)[key]
        if (typeof value !== 'string' || !value.trim()) {
            continue
        }
        try {
            rendered[key] = LiquidRenderer.renderWithHogFunctionGlobals(value, globals)
        } catch (error) {
            onError(key, error instanceof Error ? error.message : String(error))
        }
    }
    return rendered
}

/** The defaults, with each custom value that rendered to something non-empty in place of its default. */
export const resolveUtmTags = (defaults: UtmTags, rendered: unknown): UtmTags => {
    const custom = rendered && typeof rendered === 'object' ? (rendered as Record<string, unknown>) : {}
    const tags = { ...defaults }
    for (const key of UTM_KEYS) {
        const value = custom[key]
        if (typeof value === 'string' && value.trim()) {
            tags[key] = value.trim()
        }
    }
    return tags
}

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
    return html.replace(ANCHOR_TAG_REGEX, (anchor) => {
        if (UTM_OPT_OUT_REGEX.test(anchor)) {
            return anchor
        }
        return anchor.replace(
            HREF_ATTR_REGEX,
            (match, prefix: string, doubleQuoted?: string, singleQuoted?: string) => {
                const quote = doubleQuoted !== undefined ? '"' : "'"
                const tagged = addUtmTagsToUrl(
                    decodeHtmlEntitiesInHref(doubleQuoted ?? singleQuoted ?? ''),
                    tags,
                    siteHost
                )
                if (tagged === null) {
                    return match
                }
                const encoded = tagged
                    .replace(/&/g, '&amp;')
                    .replace(quote === '"' ? /"/g : /'/g, quote === '"' ? '&quot;' : '&#39;')
                return `${prefix}${quote}${encoded}${quote}`
            }
        )
    })
}
