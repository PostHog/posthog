import type { LemonTagType } from '@posthog/lemon-ui'

import type { GuidedWizardStep } from 'lib/components/GuidedWizard/GuidedWizardStepper'

import {
    OrganizationOAuthApplicationApi,
    PartnerProvisioningStatusEnumApi,
    PartnerReviewApi,
    PartnerReviewEventApi,
    ProvisioningReviewStatusEnumApi,
} from '~/generated/core/api.schemas'

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

export type ReviewStep = 'registered' | 'automated_review' | 'staff_review' | 'decision'
// Every step is done, as for an accepted app, which has nothing left to wait for.
export const REVIEW_COMPLETE = 'complete'

const DECISION_STEP_LABELS: Partial<Record<ProvisioningReviewStatusEnumApi, string>> = {
    accepted: 'Approved',
    declined: 'Declined',
    changes_requested: 'Changes requested',
    rejected: 'Blocked',
}

export interface ReviewProgress {
    steps: GuidedWizardStep<ReviewStep>[]
    currentStep: ReviewStep | typeof REVIEW_COMPLETE
}

export function reviewProgress(review: PartnerReviewApi): ReviewProgress {
    const reachedStaff =
        review.status === 'needs_human' ||
        review.timeline.some(
            (event) =>
                event.kind !== 'registered' && (event.kind !== 'automated_review' || event.status === 'needs_human')
        )
    const steps: GuidedWizardStep<ReviewStep>[] = [
        { step: 'registered', label: 'Registered' },
        { step: 'automated_review', label: 'Automated review' },
        ...(reachedStaff ? [{ step: 'staff_review' as const, label: 'PostHog staff review' }] : []),
        { step: 'decision', label: DECISION_STEP_LABELS[review.status] ?? 'Decision' },
    ]
    const currentStep =
        review.status === 'pending'
            ? 'automated_review'
            : review.status === 'needs_human'
              ? 'staff_review'
              : review.status === 'accepted'
                ? REVIEW_COMPLETE
                : 'decision'
    return { steps, currentStep }
}

const AUTOMATED_REVIEW_TITLES: Partial<Record<ProvisioningReviewStatusEnumApi, string>> = {
    accepted: 'The automated review approved the application',
    declined: 'The automated review declined the application',
    needs_human: 'The automated review sent the application to PostHog staff',
}

const STAFF_DECISION_TITLES: Partial<Record<ProvisioningReviewStatusEnumApi, string>> = {
    accepted: 'PostHog staff approved the application',
    declined: 'PostHog staff declined the application',
    changes_requested: 'PostHog staff asked for changes',
    rejected: 'PostHog staff blocked the application',
    needs_human: 'PostHog staff reopened the review',
}

export function reviewEventTitle(event: PartnerReviewEventApi): string {
    switch (event.kind) {
        case 'registered':
            return 'The application registered for provisioning'
        case 'automated_review':
            return (event.status && AUTOMATED_REVIEW_TITLES[event.status]) || 'The automated review finished'
        case 'staff_decision':
            return (event.status && STAFF_DECISION_TITLES[event.status]) || 'PostHog staff made a decision'
        case 'staff_message':
            return 'PostHog staff changed their message'
        case 'partner_note':
            return event.author ? `Note from ${event.author}` : 'Note from your organization'
    }
}
