import { ProductKey } from '~/queries/schema/schema-general'
import { type BillingProductV2Type } from '~/types'
import { OnboardingStepKey } from '~/types'

import { OnboardingUpgradeStep } from './billing/OnboardingUpgradeStep'
import { OnboardingDataWarehouseSourcesStep } from './data-warehouse/OnboardingDataWarehouseSourcesStep'
import { OnboardingAIReports } from './notifications/OnboardingAIReports'
import { OnboardingInviteTeammates } from './OnboardingInviteTeammates'
import { OnboardingFlowContext, OnboardingStepDescriptor } from './types'

// The only step keys that join a flow after it first renders. Each is gated on data that arrives
// asynchronously (billing, organization, feature flags), so a URL targeting one has to be held
// open until that data settles. `link_data` is deliberately absent: it is gated on the primary and
// secondary product keys alone, both of which are set from the URL before the step is, so it is
// either in the flow immediately or never. Keep in sync with the pushes below.
const ASYNC_TRAILING_STEP_KEYS = new Set<string>([
    OnboardingStepKey.PLANS,
    OnboardingStepKey.INVITE_TEAMMATES,
    OnboardingStepKey.AI_REPORTS,
])

/**
 * Whether a stepId could still be appended to the flow, so an unresolved URL targeting it is
 * worth holding open rather than self-correcting. Any other key either resolves against the
 * flow it was built for or never will.
 */
export function mayBeAppendedLater(stepId: string): boolean {
    // A `?` or `&` means query params fused into the step value, which is a mangled URL rather
    // than a step anything is waiting on.
    if (/[?&]/.test(stepId)) {
        return false
    }
    const [stepKey] = stepId.split(':')
    return ASYNC_TRAILING_STEP_KEYS.has(stepKey)
}

export function appendSharedTrailingSteps(
    steps: OnboardingStepDescriptor[],
    ctx: OnboardingFlowContext,
    billingProduct: BillingProductV2Type | null,
    shouldShowBilling: boolean
): OnboardingStepDescriptor[] {
    const result = [...steps]

    // Skip when DATA_WAREHOUSE is a secondary — its provider already emits the Import data step.
    if (ctx.primary === ProductKey.PRODUCT_ANALYTICS && !ctx.secondaries.includes(ProductKey.DATA_WAREHOUSE)) {
        result.push({
            id: `${OnboardingStepKey.LINK_DATA}:${ctx.primary}`,
            productKey: ctx.primary,
            stepKey: OnboardingStepKey.LINK_DATA,
            role: 'primary',
            render: () => <OnboardingDataWarehouseSourcesStep />,
        })
    }

    if (shouldShowBilling && billingProduct) {
        result.push({
            id: `${OnboardingStepKey.PLANS}:${ctx.primary}`,
            productKey: ctx.primary,
            stepKey: OnboardingStepKey.PLANS,
            role: 'primary',
            render: () => <OnboardingUpgradeStep product={billingProduct} />,
        })
    }

    if (ctx.canInviteTeammates) {
        result.push({
            id: `${OnboardingStepKey.INVITE_TEAMMATES}:${ctx.primary}`,
            productKey: ctx.primary,
            stepKey: OnboardingStepKey.INVITE_TEAMMATES,
            role: 'primary',
            render: () => <OnboardingInviteTeammates />,
        })
    }

    // Last on purpose: the lowest-stakes step, so any drop-off it causes shows up in the
    // completion metric without blocking higher-value steps.
    if (ctx.showAIReportsStep) {
        result.push({
            id: `${OnboardingStepKey.AI_REPORTS}:${ctx.primary}`,
            productKey: ctx.primary,
            stepKey: OnboardingStepKey.AI_REPORTS,
            role: 'primary',
            render: () => <OnboardingAIReports />,
        })
    }

    return result
}
