import { LemonBanner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

export function HealthEmptyState({ hasIngestedEvents }: { hasIngestedEvents: boolean }): JSX.Element {
    // Without any ingested events the checks have nothing to run against, so treat an empty result
    // set as "not set up yet" and point the user at install rather than claiming everything is fine.
    if (!hasIngestedEvents) {
        return (
            <LemonBanner
                type="info"
                action={{
                    to: urls.onboarding({
                        productKey: ProductKey.PRODUCT_ANALYTICS,
                        stepKey: OnboardingStepKey.INSTALL,
                    }),
                    children: 'Install PostHog',
                    'data-attr': 'health-empty-install',
                }}
            >
                <p className="font-semibold mb-0">Health checks have not run yet</p>
                <p className="text-sm mt-1 mb-0">
                    Health checks start once your project receives data. Install PostHog to send your first events.
                </p>
            </LemonBanner>
        )
    }

    return (
        <LemonBanner type="success">
            <p className="font-semibold mb-0">All systems healthy</p>
            <p className="text-sm mt-1 mb-0">No active health issues found for your project.</p>
        </LemonBanner>
    )
}
