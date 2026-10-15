import { SetupTaskId } from 'lib/components/ProductSetup'

import { ProductKey } from '~/queries/schema/schema-general'
import { type BillingProductV2Type, OnboardingStepKey } from '~/types'

import { OnboardingUpgradeStep } from '../billing/OnboardingUpgradeStep'
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

export function buildSimpleOnboardingFlow(
    billingProduct: BillingProductV2Type | null,
    shouldShowBilling: boolean
): OnboardingStepDescriptor[] {
    const steps: OnboardingStepDescriptor[] = [
        {
            id: `${OnboardingStepKey.INSTALL}:${SIMPLE_ONBOARDING_PRODUCT_KEY}`,
            productKey: SIMPLE_ONBOARDING_PRODUCT_KEY,
            stepKey: OnboardingStepKey.INSTALL,
            role: 'primary',
            setupTaskId: SetupTaskId.IngestFirstEvent,
            dedupKey: INSTALL_DEDUP_KEYS.POSTHOG_JS,
            render: () => (
                <OnboardingInstallStep
                    sdkInstructionMap={ProductAnalyticsSDKInstructions}
                    sdkTagOverrides={ProductAnalyticsSDKTagOverrides}
                />
            ),
        },
        {
            id: `${OnboardingStepKey.MCP}:${SIMPLE_ONBOARDING_PRODUCT_KEY}`,
            productKey: SIMPLE_ONBOARDING_PRODUCT_KEY,
            stepKey: OnboardingStepKey.MCP,
            role: 'primary',
            render: () => <OnboardingMcpStep />,
        },
    ]
    if (shouldShowBilling && billingProduct) {
        steps.push({
            id: `${OnboardingStepKey.PLANS}:${SIMPLE_ONBOARDING_PRODUCT_KEY}`,
            productKey: SIMPLE_ONBOARDING_PRODUCT_KEY,
            stepKey: OnboardingStepKey.PLANS,
            role: 'primary',
            render: () => <OnboardingUpgradeStep product={billingProduct} />,
        })
    }
    return steps
}
