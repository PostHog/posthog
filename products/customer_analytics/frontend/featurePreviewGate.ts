import { FEATURE_FLAGS } from 'lib/constants'

import { FeaturePreviewGateConfig } from '~/types'

export const customerAnalyticsFeaturePreviewGate: FeaturePreviewGateConfig = {
    flag: FEATURE_FLAGS.CUSTOMER_ANALYTICS,
    title: 'Try Customer analytics',
    description:
        'Get context about your customers. Is the number of signups going up? Are we converting free users to paid users? Need to know what the power users of a feature are? We got you covered.',
    docsURL: 'https://posthog.com/docs/customer-analytics',
}

export const customerAnalyticsAccountsFeaturePreviewGate: FeaturePreviewGateConfig = {
    flag: FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
    title: 'Try Accounts',
    description:
        'Manage and triage customer accounts: filter by tags, key-role assignment, and ownership. Track CSM, account executive, and account owner per account.',
    docsURL: 'https://posthog.com/docs/customer-analytics',
}
