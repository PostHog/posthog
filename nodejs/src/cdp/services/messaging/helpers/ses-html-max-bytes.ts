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

const escapedQueryBytes = (params: Record<string, string>): number =>
    escapedHtmlByteLength(
        Object.entries(params)
            .filter(([, value]) => value)
            .map(([key, value]) => `&${key}=${encodeURIComponent(value)}`)
            .join('')
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
        anchors * growthPerAnchor(utmTags, invocation.id, anchors) +
        longestOpenPixelBytes(invocation, signer) +
        Buffer.byteLength(maybeAddPreheaderToEmail('', preheader), 'utf8')
    )
}
