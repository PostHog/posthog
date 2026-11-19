import { CyclotronJobInvocationHogFunction } from '~/cdp/types'

import { addTrackingToEmail } from '../email-tracking.service'
import { addTrackingToEmailRegex, addUtmTagsToEmailRegex, addWorkflowRunTagToEmailRegex } from './link-passes-regex'
import { maybeAddPreheaderToEmail } from './preheader'
import { EmailTrackingCodeSigner } from './tracking-code'
import {
    UtmTags,
    WorkflowRunTag,
    addUtmTagsToEmail,
    addWorkflowRunTagToEmail,
    renderUtmOverrides,
    resolveUtmTags,
} from './utm'

export type UtmTagging = {
    tags: UtmTags
    siteUrl: string
    fixedScanner: boolean
}

export type SesTracking = {
    invocation: CyclotronJobInvocationHogFunction
    signer: EmailTrackingCodeSigner
    isTest: boolean
    linkParser: boolean
}

export const utmTagsFor = (
    invocation: CyclotronJobInvocationHogFunction,
    onRenderError: (key: string, message: string) => void,
    deadline?: AbortSignal
): UtmTags | null => {
    const metadata = invocation.hogFunction.metadata
    if (metadata?.utm_tags_enabled !== true) {
        return null
    }
    return resolveUtmTags(
        {
            utm_source: 'posthog',
            utm_medium: 'email',
            utm_campaign: metadata.hog_flow_name ?? invocation.hogFunction.name,
            utm_content: metadata.hog_flow_action_name ?? '',
        },
        renderUtmOverrides(metadata.utm_params, invocation.state.globals, onRenderError, deadline)
    )
}

const addUtmTags = (html: string, utm: UtmTagging, linkParser: boolean): string =>
    utm.fixedScanner && !linkParser
        ? addUtmTagsToEmailRegex(html, utm.tags, utm.siteUrl)
        : addUtmTagsToEmail(html, utm.tags, utm.siteUrl, utm.fixedScanner)

export const tagEmailLinks = (
    html: string,
    utm: UtmTagging | null,
    runTag: WorkflowRunTag | null,
    linkParser: boolean
): string => {
    const utmTagged = utm ? addUtmTags(html, utm, linkParser) : html
    if (!runTag) {
        return utmTagged
    }
    return linkParser ? addWorkflowRunTagToEmail(utmTagged, runTag) : addWorkflowRunTagToEmailRegex(utmTagged, runTag)
}

export const trackLinks = (linkParser: boolean): typeof addTrackingToEmail =>
    linkParser ? addTrackingToEmail : addTrackingToEmailRegex

export const htmlForSes = (html: string, tracking: SesTracking | null, preheader?: string): string =>
    maybeAddPreheaderToEmail(
        tracking
            ? trackLinks(tracking.linkParser)(html, tracking.invocation, tracking.signer, tracking.isTest, 'ses')
            : html,
        preheader
    )
