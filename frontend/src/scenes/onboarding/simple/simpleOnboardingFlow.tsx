import { SetupTaskId } from 'lib/components/ProductSetup'

import { ProductKey } from '~/queries/schema/schema-general'
import { type BillingProductV2Type, OnboardingStepKey } from '~/types'

import { OnboardingUpgradeStep } from '../billing/OnboardingUpgradeStep'
import { OnboardingInviteTeammates } from '../OnboardingInviteTeammates'
import { OnboardingInstallStep } from '../sdks/OnboardingInstallStep'
import {
    ProductAnalyticsSDKInstructions,
    ProductAnalyticsSDKTagOverrides,
} from '../sdks/product-analytics/ProductAnalyticsSDKInstructions'
import { INSTALL_DEDUP_KEYS, type OnboardingStepDescriptor } from '../types'
import { OnboardingMcpStep } from './OnboardingMcpStep'

/**
 * The simple onboarding is product-agnostic. Its steps are booked under product analytics, because
 * completing that product is what stops the app from sending the user back into onboarding.
 */
export const SIMPLE_ONBOARDING_PRODUCT_KEY = ProductKey.PRODUCT_ANALYTICS

/** The posthog-js install step with Wizard up front, booked under the given product. */
function buildWizardInstallStep(productKey: ProductKey): OnboardingStepDescriptor {
    return {
        id: `${OnboardingStepKey.INSTALL}:${productKey}`,
        productKey,
        stepKey: OnboardingStepKey.INSTALL,
        label: 'Install PostHog',
        role: 'primary',
        setupTaskId: SetupTaskId.IngestFirstEvent,
        dedupKey: INSTALL_DEDUP_KEYS.POSTHOG_JS,
        render: () => (
            <OnboardingInstallStep
                sdkInstructionMap={ProductAnalyticsSDKInstructions}
                sdkTagOverrides={ProductAnalyticsSDKTagOverrides}
                compact
            />
        ),
    }
}

export function buildSimpleOnboardingFlow(
    billingProduct: BillingProductV2Type | null,
    shouldShowBilling: boolean,
    canInviteTeammates: boolean
): OnboardingStepDescriptor[] {
    const steps: OnboardingStepDescriptor[] = [
        buildWizardInstallStep(SIMPLE_ONBOARDING_PRODUCT_KEY),
        {
            id: `${OnboardingStepKey.MCP}:${SIMPLE_ONBOARDING_PRODUCT_KEY}`,
            productKey: SIMPLE_ONBOARDING_PRODUCT_KEY,
            stepKey: OnboardingStepKey.MCP,
            label: 'Connect your AI agent',
            role: 'primary',
            render: () => <OnboardingMcpStep />,
        },
    ]
    if (shouldShowBilling && billingProduct) {
        steps.push({
            id: `${OnboardingStepKey.PLANS}:${SIMPLE_ONBOARDING_PRODUCT_KEY}`,
            productKey: SIMPLE_ONBOARDING_PRODUCT_KEY,
            stepKey: OnboardingStepKey.PLANS,
            label: 'Select a plan',
            role: 'primary',
            render: () => <OnboardingUpgradeStep product={billingProduct} />,
        })
    }
    if (canInviteTeammates) {
        steps.push({
            id: `${OnboardingStepKey.INVITE_TEAMMATES}:${SIMPLE_ONBOARDING_PRODUCT_KEY}`,
            productKey: SIMPLE_ONBOARDING_PRODUCT_KEY,
            stepKey: OnboardingStepKey.INVITE_TEAMMATES,
            label: 'Invite your team',
            role: 'primary',
            render: () => <OnboardingInviteTeammates />,
        })
    }
    return steps
}
