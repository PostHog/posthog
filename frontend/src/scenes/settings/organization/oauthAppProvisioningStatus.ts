import type { LemonTagType } from '@posthog/lemon-ui'

import { OrganizationOAuthApplicationApi, PartnerProvisioningStatusEnumApi } from '~/generated/core/api.schemas'

export const PROVISIONING_STATUS_LABELS: Record<PartnerProvisioningStatusEnumApi, string> = {
    not_a_partner: 'Not a partner',
    in_review: 'In review',
    waiting_for_staff: 'Waiting for PostHog staff',
    changes_requested: 'Changes requested',
    declined: 'Declined',
    on: 'On',
    off: 'Off',
    blocked: 'Blocked',
}

export const PROVISIONING_STATUS_TAG_TYPES: Record<PartnerProvisioningStatusEnumApi, LemonTagType> = {
    not_a_partner: 'muted',
    in_review: 'highlight',
    waiting_for_staff: 'warning',
    changes_requested: 'highlight',
    declined: 'warning',
    on: 'success',
    off: 'warning',
    blocked: 'danger',
}

// What the app's owners can expect next, for each status.
export const PROVISIONING_STATUS_NEXT_STEPS: Record<PartnerProvisioningStatusEnumApi, string> = {
    not_a_partner: 'This application signs people in with PostHog. It does not create accounts or provision resources.',
    in_review: 'PostHog is reviewing this application. Most reviews finish within minutes.',
    waiting_for_staff:
        'PostHog staff are reviewing this application, which can take longer. Send them a note if you can tell them more about it.',
    changes_requested:
        'PostHog staff need changes or more information before this application can provision. Answer below, and your note goes back to them.',
    declined:
        "PostHog didn't approve this application for provisioning. Once you've changed it, or if there's something staff should know, ask for another review below.",
    on: 'This application can create accounts and provision resources.',
    off: 'Provisioning is off for this application. Contact support to turn it on.',
    blocked:
        "PostHog blocked provisioning for this application. Registering again or asking for another review doesn't lift the block. Contact support if you think this is a mistake.",
}

// The statuses where only PostHog can move the application forward, outside its review.
export const PROVISIONING_STATUSES_NEEDING_SUPPORT = new Set<PartnerProvisioningStatusEnumApi>(['off', 'blocked'])

export const PROVISIONING_STATUSES_TAKING_A_NOTE = new Set<PartnerProvisioningStatusEnumApi>([
    'waiting_for_staff',
    'changes_requested',
    'declined',
])

export const REVIEW_NOTE_SUBMIT_LABELS: Partial<Record<PartnerProvisioningStatusEnumApi, string>> = {
    waiting_for_staff: 'Send note',
    changes_requested: 'Send answer',
    declined: 'Ask for another review',
}

export interface OAuthAppActions {
    showsProvisioning: boolean
    takesANote: boolean
    needsSupport: boolean
    canRequestVerification: boolean
}

export function oauthAppActions(app: OrganizationOAuthApplicationApi): OAuthAppActions {
    return {
        showsProvisioning: app.is_cimd_client || app.provisioning_status !== 'not_a_partner',
        takesANote: !!app.provisioning_review && PROVISIONING_STATUSES_TAKING_A_NOTE.has(app.provisioning_status),
        needsSupport: PROVISIONING_STATUSES_NEEDING_SUPPORT.has(app.provisioning_status),
        canRequestVerification: !!app.is_cimd_client && !app.is_verified,
    }
}
