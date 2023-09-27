import { OnboardingStep } from './OnboardingStep'
import { PlanComparison } from 'scenes/billing/PlanComparison'
import { useActions, useValues } from 'kea'
import { billingLogic } from 'scenes/billing/billingLogic'
import { onboardingLogic } from './onboardingLogic'
import { BillingProductV2Type } from '~/types'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { BillingHero } from 'scenes/billing/BillingHero'
import { LemonButton } from '@posthog/lemon-ui'
import { getUpgradeProductLink } from 'scenes/billing/billing-utils'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { IconCheckCircleOutline } from 'lib/lemon-ui/icons'
import { StarHog } from 'lib/components/hedgehogs'

export const OnboardingBillingStep = ({ product }: { product: BillingProductV2Type }): JSX.Element => {
    const { billing, redirectPath } = useValues(billingLogic)
    const { productKey } = useValues(onboardingLogic)
    const { currentAndUpgradePlans } = useValues(billingProductLogic({ product }))
    const { reportBillingUpgradeClicked } = useActions(eventUsageLogic)
    const plan = currentAndUpgradePlans?.upgradePlan

    return (
        <OnboardingStep
            title="Add credit card details"
            showSkip={!product.subscribed}
            continueOverride={
                product?.subscribed ? undefined : (
                    <LemonButton
                        // TODO: redirect path won't work properly until navigation is properly set up
                        to={getUpgradeProductLink(product, plan.plan_key || '', redirectPath, true)}
                        type="primary"
                        center
                        disableClientSideRouting
                        onClick={() => {
                            reportBillingUpgradeClicked(product.type)
                        }}
                    >
                        Upgrade to paid
                    </LemonButton>
                )
            }
        >
            {billing?.products && productKey && product ? (
                <div className="mt-6">
                    {product.subscribed ? (
                        <div className="mb-8">
                            <div className="bg-success-highlight rounded-lg p-6 flex justify-between items-center mb-8">
                                <div className="flex gap-x-4">
                                    <IconCheckCircleOutline className="text-success text-3xl mb-6" />
                                    <div>
                                        <h3 className="text-lg font-bold mb-1 text-left">Subscribe successful</h3>
                                        <p className="mx-0 mb-0">You're all ready to use {product.name}.</p>
                                    </div>
                                </div>
                                <div className="h-20">
                                    <StarHog className="h-full w-full" />
                                </div>
                            </div>
                        </div>
                    ) : (
                        <>
                            <BillingHero />
                            <PlanComparison product={product} includeAddons />
                        </>
                    )}
                </div>
            ) : (
                <Spinner className="text-lg" />
            )}
        </OnboardingStep>
    )
}
