import type { BillingAlertConfig } from 'lib/logic/billing/billingLogic'
import { buildUsageLimitApproachingMessage, buildUsageLimitReachedMessage } from 'lib/logic/billing/usageLimits'

import type { FakeBillingAlert } from './superpowersLogic'

/** Mirrors the alerts billingLogic raises, built with the same message helpers so the text matches. */
export function buildFakeBillingAlert(fake: FakeBillingAlert): BillingAlertConfig | null {
    switch (fake) {
        case 'usage_limit_reached':
            return {
                kind: 'usage_limit',
                status: 'error',
                ...buildUsageLimitReachedMessage([
                    { type: 'product_analytics', name: 'Product analytics', subscribed: true },
                ]),
            }
        case 'usage_limit_approaching':
            return {
                kind: 'usage_limit',
                status: 'info',
                ...buildUsageLimitApproachingMessage([
                    { type: 'session_replay', name: 'Session replay', percentage_usage: 0.85 },
                ]),
            }
        case 'trial':
            return {
                kind: 'trial',
                status: 'info',
                title: "Your free trial for the Teams plan ends in 3 days. Your service will continue without interruption, and you'll be charged for the Teams plan.",
                message: 'Questions? Reach out to sales at sales@posthog.com.',
            }
        case 'none':
            return null
    }
}
