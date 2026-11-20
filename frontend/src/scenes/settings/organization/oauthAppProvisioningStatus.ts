import type { LemonTagType } from '@posthog/lemon-ui'

import { PartnerProvisioningStatusEnumApi } from '~/generated/core/api.schemas'

export const PROVISIONING_STATUS_LABELS: Record<PartnerProvisioningStatusEnumApi, string> = {
    not_a_partner: 'Not a partner',
    in_review: 'In review',
    waiting_for_staff: 'Waiting for PostHog staff',
    on: 'On',
    off: 'Off',
    blocked: 'Blocked',
}

export const PROVISIONING_STATUS_TAG_TYPES: Record<PartnerProvisioningStatusEnumApi, LemonTagType> = {
    not_a_partner: 'muted',
    in_review: 'highlight',
    waiting_for_staff: 'warning',
    on: 'success',
    off: 'warning',
    blocked: 'danger',
}

// What the app's owners can expect next, for each status.
export const PROVISIONING_STATUS_NEXT_STEPS: Record<PartnerProvisioningStatusEnumApi, string> = {
    not_a_partner: 'This application signs people in with PostHog. It does not create accounts or provision resources.',
    in_review: 'PostHog is reviewing this application. Most reviews finish within minutes.',
    waiting_for_staff:
        'PostHog staff are reviewing this application, which can take longer. Contact support if you can tell us more about it.',
    on: 'This application can create accounts and provision resources.',
    off: 'Provisioning is off for this application. Contact support to turn it on.',
    blocked:
        "PostHog blocked provisioning for this application. Registering again doesn't lift the block. Contact support if you think this is a mistake.",
}

// The statuses where only PostHog can move the application forward.
export const PROVISIONING_STATUSES_NEEDING_SUPPORT = new Set<PartnerProvisioningStatusEnumApi>([
    'waiting_for_staff',
    'off',
    'blocked',
])
