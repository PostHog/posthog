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

function simpleStep(
    stepKey: OnboardingStepKey,
    label: string,
    render: () => React.ReactElement,
    extra: Partial<OnboardingStepDescriptor> = {}
): OnboardingStepDescriptor {
    return {
        id: `${stepKey}:${SIMPLE_ONBOARDING_PRODUCT_KEY}`,
        productKey: SIMPLE_ONBOARDING_PRODUCT_KEY,
        stepKey,
        label,
        role: 'primary',
        render,
        ...extra,
    }
}

export function buildSimpleOnboardingFlow(
    billingProduct: BillingProductV2Type | null,
    shouldShowBilling: boolean,
    canInviteTeammates: boolean
): OnboardingStepDescriptor[] {
    return [
        simpleStep(
            OnboardingStepKey.INSTALL,
            'Install PostHog',
            () => (
                <OnboardingInstallStep
                    sdkInstructionMap={ProductAnalyticsSDKInstructions}
                    sdkTagOverrides={ProductAnalyticsSDKTagOverrides}
                    compact
                />
            ),
            { setupTaskId: SetupTaskId.IngestFirstEvent, dedupKey: INSTALL_DEDUP_KEYS.POSTHOG_JS }
        ),
        simpleStep(OnboardingStepKey.MCP, 'Connect your AI agent', () => <OnboardingMcpStep />),
        ...(shouldShowBilling && billingProduct
            ? [
                  simpleStep(OnboardingStepKey.PLANS, 'Select a plan', () => (
                      <OnboardingUpgradeStep product={billingProduct} />
                  )),
              ]
            : []),
        ...(canInviteTeammates
            ? [simpleStep(OnboardingStepKey.INVITE_TEAMMATES, 'Invite your team', () => <OnboardingInviteTeammates />)]
            : []),
    ]
}
