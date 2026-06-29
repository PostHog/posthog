import { ProductKey } from '~/queries/schema/schema-general'
import { type BillingProductV2Type } from '~/types'
import { OnboardingStepKey } from '~/types'

import { OnboardingUpgradeStep } from './billing/OnboardingUpgradeStep'
import { OnboardingDataWarehouseSourcesStep } from './data-warehouse/OnboardingDataWarehouseSourcesStep'
import { OnboardingInviteTeammates } from './OnboardingInviteTeammates'
import { OnboardingFlowContext, OnboardingStepDescriptor } from './types'

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

    return result
}
