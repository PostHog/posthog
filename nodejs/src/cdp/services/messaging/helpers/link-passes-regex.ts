import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { isDevEnv, isTestEnv } from '~/common/utils/env-utils'

import { isSensitiveMessage } from '../../hogflows/hogflow-sensitivity'
import {
    EmailTrackingMode,
    decodeHtmlEntitiesInHref,
    isJavascriptHref,
    openPixelTag,
    resolveEmailTrackingDistinctId,
} from '../email-tracking.service'
import { escapeHtml } from './escape-html'
import { WORKFLOW_RUN_PARAM, removeWorkflowRunTag } from './link-tags'
import { SES_LINK_INDEX_TAG } from './ses'
import { EmailTrackingCodeSigner } from './tracking-code'
import {
    UtmTags,
    WorkflowRunTag,
    addTagsToUrl,
    hostOf,
    parseTaggableUrl,
    registrableDomainOf,
    trimUrlWhitespace,
} from './utm'

// The link passes as they ran before the HTML parser in href-anchors.ts, kept byte for byte for teams
// outside CDP_EMAIL_LINK_PARSER_TEAMS. Delete this module once that allowlist is '*' in every region.

type HrefAnchor = {
    html: string
    href: string
}

type IndexFinder = (from: number) => number

type HrefValue = { href: string; end: number }

type ValueStream = {
    nextValueEnd: IndexFinder
    nextTagEnd: IndexFinder
    nextAnchorClose: IndexFinder
}

const memoizedFinder = (html: string, pattern: RegExp): IndexFinder => {
    const search = new RegExp(pattern)
    let searchedFrom = -1
    let found = -1
    return (from) => {
        if (searchedFrom === -1 || from < searchedFrom || (found !== -1 && from > found)) {
            search.lastIndex = from
            found = search.exec(html)?.index ?? -1
            searchedFrom = from
        }
        return found
    }
}

const valueStream = (html: string, valueEnd: RegExp): ValueStream => ({
    nextValueEnd: memoizedFinder(html, valueEnd),
    nextTagEnd: memoizedFinder(html, />/g),
    nextAnchorClose: memoizedFinder(html, /<\/a>/gi),
})

const hrefMatcher = (html: string): ((hrefStart: number) => HrefValue | null) => {
    const assignment = /\s*=\s*/y
    const javascriptScheme = /javascript:/iy
    const doubleQuoted = valueStream(html, /"/g)
    const singleQuoted = valueStream(html, /'/g)
    const unquoted = valueStream(html, /['">\s]/g)

    const isJavascriptAt = (position: number): boolean => {
        javascriptScheme.lastIndex = position
        return javascriptScheme.test(html)
    }

    const quotedValue = (valueStart: number, stream: ValueStream): HrefValue | null => {
        if (isJavascriptAt(valueStart + 1)) {
            return null
        }
        const closingQuote = stream.nextValueEnd(valueStart + 1)
        return closingQuote === -1 ? null : { href: html.slice(valueStart + 1, closingQuote), end: closingQuote + 1 }
    }

    const unquotedValue = (valueStart: number): HrefValue | null => {
        if (isJavascriptAt(valueStart)) {
            return null
        }
        const stop = unquoted.nextValueEnd(valueStart)
        const end = stop === -1 ? html.length : stop
        return end === valueStart ? null : { href: html.slice(valueStart, end), end }
    }

    return (hrefStart) => {
        assignment.lastIndex = hrefStart + 'href'.length
        if (!assignment.test(html)) {
            return null
        }
        const valueStart = assignment.lastIndex
        const quote = html[valueStart]
        const stream = quote === '"' ? doubleQuoted : quote === "'" ? singleQuoted : unquoted
        const value = stream === unquoted ? unquotedValue(valueStart) : quotedValue(valueStart, stream)
        if (!value) {
            return null
        }
        const tagEnd = stream.nextTagEnd(value.end)
        const anchorClose = tagEnd === -1 ? -1 : stream.nextAnchorClose(tagEnd + 1)
        return anchorClose === -1 ? null : { href: value.href, end: anchorClose + '</a>'.length }
    }
}

const replaceHrefAnchors = (html: string, replace: (anchor: HrefAnchor) => string): string => {
    const nextAnchorStart = memoizedFinder(html, /<a\b/gi)
    const nextOpeningTagEnd = memoizedFinder(html, />/g)
    const nextHref = memoizedFinder(html, /\bhref/gi)
    const hrefMatchAt = hrefMatcher(html)

    const pieces: string[] = []
    let copiedUpTo = 0
    let searchFrom = 0
    let unscannedHrefsFrom = 0
    let lastMatch: { hrefStart: number; match: HrefValue } | null = null

    for (let start = nextAnchorStart(searchFrom); start !== -1; start = nextAnchorStart(searchFrom)) {
        const attributesStart = start + '<a'.length
        const openingTagEnd = nextOpeningTagEnd(attributesStart)
        const lastHrefStart = openingTagEnd === -1 ? html.length : openingTagEnd
        const firstHrefStart = Math.max(unscannedHrefsFrom, attributesStart)
        for (let hrefStart = nextHref(firstHrefStart); hrefStart !== -1 && hrefStart <= lastHrefStart; ) {
            const match = hrefMatchAt(hrefStart)
            if (match) {
                lastMatch = { hrefStart, match }
            }
            hrefStart = nextHref(hrefStart + 1)
        }
        unscannedHrefsFrom = Math.max(unscannedHrefsFrom, lastHrefStart + 1)
        if (!lastMatch || lastMatch.hrefStart < attributesStart) {
            searchFrom = start + 1
            continue
        }
        const { href, end } = lastMatch.match
        pieces.push(html.slice(copiedUpTo, start), replace({ html: html.slice(start, end), href }))
        copiedUpTo = searchFrom = end
    }
    pieces.push(html.slice(copiedUpTo))
    return pieces.join('')
}

// `clicktracking="off"` is the ESP de-facto standard; `data-ph-no-track` is our name.
const CLICK_TRACKING_OPT_OUT_REGEX = /\bclicktracking\s*=\s*["']?off["']?|\bdata-ph-no-track\b/i
const SES_NO_TRACK_ATTR_REGEX = /\bses:no-track\b/i

const hasClickTrackingOptOut = (openingTag: string): boolean => CLICK_TRACKING_OPT_OUT_REGEX.test(openingTag)

const hasSesNoTrack = (openingTag: string): boolean => SES_NO_TRACK_ATTR_REGEX.test(openingTag)

const isNeverClickTracked = (openingTag: string): boolean =>
    hasClickTrackingOptOut(openingTag) || hasSesNoTrack(openingTag)

// Matches an existing `ses:tags` attribute so our link tag can be merged into its value.
const SES_TAGS_ATTR_REGEX = /\bses:tags\s*=\s*(?:"([^"]*)"|'([^']*)'|([^'">\s]+))/i

const addAttributeToOpeningTag = (openingTag: string, attribute: string): string => {
    if (!openingTag.endsWith('>')) {
        return openingTag
    }
    const attributes = openingTag.slice(0, -1)
    const withoutSelfClose = attributes.endsWith('/') ? attributes.slice(0, -1) : attributes
    return `${withoutSelfClose.trimEnd()} ${attribute}>`
}

const withSesLinkIndexTag = (openingTag: string, linkIndex: number): string => {
    const tag = `${SES_LINK_INDEX_TAG}:${linkIndex}`
    const existing = openingTag.match(SES_TAGS_ATTR_REGEX)
    if (!existing) {
        return addAttributeToOpeningTag(openingTag, `ses:tags="${tag}"`)
    }
    const value = existing[1] ?? existing[2] ?? existing[3] ?? ''
    return openingTag.replace(SES_TAGS_ATTR_REGEX, () => `ses:tags="${value ? `${value};` : ''}${tag}"`)
}

export const addTrackingToEmailRegex = (
    html: string,
    invocation: CyclotronJobInvocationHogFunction,
    signer: EmailTrackingCodeSigner,
    isTest = false,
    mode: EmailTrackingMode = 'redirect'
): string => {
    const distinctId = isDevEnv() || isTestEnv() ? resolveEmailTrackingDistinctId(invocation) : undefined
    const trackingInvocation = { ...invocation, distinctId, workflowVersion: invocation.state.renderedWorkflowVersion }
    const trackingUrl = signer.pixelUrl(trackingInvocation, isTest)

    let anchorIndex = 0
    const allLinksOptedOut = !(invocation.state?.send?.tracking.clicks ?? !isSensitiveMessage(invocation))

    html = replaceHrefAnchors(html, ({ html: m, href: rawHref }) => {
        const linkIndex = anchorIndex++
        const href = decodeHtmlEntitiesInHref(rawHref)
        if (isJavascriptHref(href)) {
            return m
        }
        const openingTag = m.match(/^<a\b[^>]*>/i)?.[0] ?? ''
        const optedOut = allLinksOptedOut || hasClickTrackingOptOut(openingTag)

        if (mode === 'ses') {
            if (optedOut) {
                return hasSesNoTrack(openingTag)
                    ? m
                    : addAttributeToOpeningTag(openingTag, 'ses:no-track') + m.slice(openingTag.length)
            }
            return withSesLinkIndexTag(openingTag, linkIndex) + m.slice(openingTag.length)
        }

        if (optedOut) {
            return m
        }
        const tracked = signer.redirectUrl(trackingInvocation, href, isTest)
        return m.replace(/\bhref\s*=\s*(?:"[^"]*"|'[^']*'|[^'">\s]+)/i, `href="${tracked}"`)
    })

    return html.replace('</body>', `${openPixelTag(trackingUrl)}</body>`)
}

const ATTRIBUTE_REGEX = /\s([^\s"'<>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\t\n\f\r >]+)))?/g

type Attribute = RegExpMatchArray

type Anchor = {
    html: string
    attributes: Attribute[]
}

type LinkTagger = {
    isOptedOut: (anchor: Anchor) => boolean
    tagUrl: (url: string) => string | null
}

const attributesOf = (anchor: string): Attribute[] => [...anchor.matchAll(ATTRIBUTE_REGEX)]

const attributeName = (attribute: Attribute): string => attribute[1].toLowerCase()

const attributeValue = (attribute: Attribute): string | undefined => attribute[2] ?? attribute[3] ?? attribute[4]

const isOptedOutOfUtmTags = ({ attributes }: Anchor): boolean =>
    attributes.some((attribute) => attributeName(attribute) === 'data-ph-no-utm')

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

const tagAnchor = (anchor: string, tagger: LinkTagger): string => {
    const attributes = attributesOf(anchor)
    if (tagger.isOptedOut({ html: anchor, attributes })) {
        return anchor
    }
    const href = attributes.find((attribute) => attributeName(attribute) === 'href')
    const value = href ? attributeValue(href) : undefined
    if (!href || value === undefined) {
        return anchor
    }
    const tagged = tagger.tagUrl(trimUrlWhitespace(decodeHtmlEntitiesInHref(value)))
    if (tagged === null) {
        return anchor
    }
    const quote = href[3] !== undefined ? "'" : '"'
    const encoded = escapeHtml(tagged)
    const start = href.index! + href[0].indexOf('=')
    return anchor.slice(0, start) + `=${quote}${encoded}${quote}` + anchor.slice(href.index! + href[0].length)
}

const findAnchorStart = (html: string, from: number): number => {
    const anchorStart = /<a/gi
    anchorStart.lastIndex = from
    return anchorStart.exec(html)?.index ?? -1
}

const addTagsToEmailLinks = (html: string, tagger: LinkTagger): string => {
    let output = ''
    let cursor = 0
    while (cursor < html.length) {
        const start = findAnchorStart(html, cursor)
        if (start === -1) {
            break
        }
        const after = html[start + 2]
        if (after !== undefined && !/[\s>/]/.test(after)) {
            output += html.slice(cursor, start + 2)
            cursor = start + 2
            continue
        }
        const end = findTagEnd(html, start + 2)
        if (end === -1) {
            break
        }
        output += html.slice(cursor, start) + tagAnchor(html.slice(start, end + 1), tagger)
        cursor = end + 1
    }
    return output + html.slice(cursor)
}

export const addUtmTagsToEmailRegex = (html: string, tags: UtmTags, siteUrl: string): string => {
    const siteHost = hostOf(siteUrl)
    return addTagsToEmailLinks(html, {
        isOptedOut: isOptedOutOfUtmTags,
        tagUrl: (url) => addTagsToUrl(url, tags, (parsed) => parsed.host !== siteHost),
    })
}

export const addWorkflowRunTagToEmailRegex = (
    html: string,
    { runId, senderEmail, siteUrl }: WorkflowRunTag
): string => {
    const senderDomain = registrableDomainOf(senderEmail.slice(senderEmail.lastIndexOf('@') + 1))
    if (!senderDomain) {
        return html
    }
    const siteHost = hostOf(siteUrl)
    const isOnSenderDomain = (parsed: URL): boolean =>
        parsed.host !== siteHost && registrableDomainOf(parsed.hostname) === senderDomain
    return addTagsToEmailLinks(html, {
        isOptedOut: ({ html: anchor }) => isNeverClickTracked(anchor),
        tagUrl: (url) => {
            if (runId !== null) {
                return addTagsToUrl(removeWorkflowRunTag(url), { [WORKFLOW_RUN_PARAM]: runId }, isOnSenderDomain)
            }
            const stripped = removeWorkflowRunTag(url)
            return stripped !== url && parseTaggableUrl(stripped, isOnSenderDomain) ? stripped : null
        },
    })
}
