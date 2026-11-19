import { CyclotronJobInvocationHogFunction } from '~/cdp/types'

import { openPixelTag, resolveEmailEngagementDistinctId } from '../email-tracking.service'
import { escapedHtmlByteLength } from './escape-html'
import { WORKFLOW_RUN_PARAM } from './link-tags'
import { maybeAddPreheaderToEmail } from './preheader'
import { SES_LINK_INDEX_TAG } from './ses'
import { EmailTrackingCodeSigner } from './tracking-code'
import { UtmTags } from './utm'

export type SesHtmlInputs = {
    utmTags: UtmTags | null
    invocation: CyclotronJobInvocationHogFunction
    signer: EmailTrackingCodeSigner
    preheader?: string
}

const QUOTES_A_RETAGGED_HREF_GAINS = 2
const SES_LINK_ATTRIBUTE_GROWTH = Math.max(` ses:tags="${SES_LINK_INDEX_TAG}:"`.length, ' ses:no-track'.length)
const LONGEST_WORKFLOW_VERSION = Number.MAX_SAFE_INTEGER
const anchorCount = (html: string): number => {
    const anchorStart = /<a/gi
    let anchors = 0
    while (anchorStart.exec(html) !== null) {
        anchors++
    }
    return anchors
}

const ASCII_ESCAPED_URI_COMPONENT_BYTES = Uint8Array.from({ length: 0x80 }, (_, code) =>
    escapedHtmlByteLength(encodeURIComponent(String.fromCharCode(code)))
)
const isHighSurrogate = (code: number): boolean => code >= 0xd800 && code <= 0xdbff
const isLowSurrogate = (code: number): boolean => code >= 0xdc00 && code <= 0xdfff

const escapedUriComponentBytes = (value: string): number => {
    let bytes = 0
    for (let index = 0; index < value.length; index++) {
        const code = value.charCodeAt(index)
        if (code < 0x80) {
            bytes += ASCII_ESCAPED_URI_COMPONENT_BYTES[code]
        } else if (code < 0x800) {
            bytes += 6
        } else if (isHighSurrogate(code) && isLowSurrogate(value.charCodeAt(index + 1))) {
            bytes += 12
            index++
        } else if (isHighSurrogate(code) || isLowSurrogate(code)) {
            throw new URIError('URI malformed')
        } else {
            bytes += 9
        }
    }
    return bytes
}

const ESCAPED_AMPERSAND_BYTES = escapedHtmlByteLength('&')

const escapedQueryBytes = (params: Record<string, string>): number =>
    Object.entries(params)
        .filter(([, value]) => value)
        .reduce(
            (total, [key, value]) =>
                total + ESCAPED_AMPERSAND_BYTES + escapedHtmlByteLength(`${key}=`) + escapedUriComponentBytes(value),
            0
        )

const growthPerAnchor = (utmTags: UtmTags | null, runId: string, anchors: number): number =>
    (utmTags ? QUOTES_A_RETAGGED_HREF_GAINS + escapedQueryBytes(utmTags) : 0) +
    QUOTES_A_RETAGGED_HREF_GAINS +
    escapedQueryBytes({ [WORKFLOW_RUN_PARAM]: runId }) +
    SES_LINK_ATTRIBUTE_GROWTH +
    String(anchors).length

const longestOpenPixelBytes = (
    invocation: CyclotronJobInvocationHogFunction,
    signer: EmailTrackingCodeSigner
): number =>
    Buffer.byteLength(
        openPixelTag(
            signer.pixelUrl(
                {
                    ...invocation,
                    distinctId: resolveEmailEngagementDistinctId(invocation),
                    workflowVersion: LONGEST_WORKFLOW_VERSION,
                },
                true
            )
        ),
        'utf8'
    )

export const sesHtmlMaxBytes = (html: string, { utmTags, invocation, signer, preheader }: SesHtmlInputs): number => {
    const anchors = anchorCount(html)
    return (
        escapedHtmlByteLength(html) +
        (anchors === 0 ? 0 : anchors * growthPerAnchor(utmTags, invocation.id, anchors)) +
        longestOpenPixelBytes(invocation, signer) +
        Buffer.byteLength(maybeAddPreheaderToEmail('', preheader), 'utf8')
    )
}
