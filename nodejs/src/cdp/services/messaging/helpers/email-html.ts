import { CyclotronJobInvocationHogFunction } from '~/cdp/types'

import { addTrackingToEmail } from '../email-tracking.service'
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

export const tagEmailLinks = (html: string, utm: UtmTagging | null, runTag: WorkflowRunTag | null): string => {
    const utmTagged = utm ? addUtmTagsToEmail(html, utm.tags, utm.siteUrl, utm.fixedScanner) : html
    return runTag ? addWorkflowRunTagToEmail(utmTagged, runTag) : utmTagged
}

export const htmlForSes = (html: string, tracking: SesTracking | null, preheader?: string): string =>
    maybeAddPreheaderToEmail(
        tracking ? addTrackingToEmail(html, tracking.invocation, tracking.signer, tracking.isTest, 'ses') : html,
        preheader
    )
