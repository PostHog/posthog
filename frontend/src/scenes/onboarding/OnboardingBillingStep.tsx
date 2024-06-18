import { IconCheckCircle } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { BillingUpgradeCTA } from 'lib/components/BillingUpgradeCTA'
import { StarHog } from 'lib/components/hedgehogs'
import { FEATURE_FLAGS } from 'lib/constants'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useState } from 'react'
import { AllProductsPlanComparison } from 'scenes/billing/AllProductsPlanComparison'
import { getUpgradeProductLink } from 'scenes/billing/billing-utils'
import { BillingHero } from 'scenes/billing/BillingHero'
import { billingLogic } from 'scenes/billing/billingLogic'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'
import { PlanComparison } from 'scenes/billing/PlanComparison'

import { BillingProductV2Type } from '~/types'

import { onboardingLogic, OnboardingStepKey } from './onboardingLogic'
import { OnboardingStep } from './OnboardingStep'

export const OnboardingBillingStep = ({
    product,
    stepKey = OnboardingStepKey.PLANS,
}: {
    product: BillingProductV2Type
    stepKey?: OnboardingStepKey
}): JSX.Element => {
    const { featureFlags } = useValues(featureFlagLogic)
    const { billing, redirectPath } = useValues(billingLogic)
    const { productKey } = useValues(onboardingLogic)
    const { currentAndUpgradePlans } = useValues(billingProductLogic({ product }))
    const { reportBillingUpgradeClicked } = useActions(eventUsageLogic)
    const plan = currentAndUpgradePlans?.upgradePlan
    const currentPlan = currentAndUpgradePlans?.currentPlan

    const [showPlanComp, setShowPlanComp] = useState(false)

    const action = featureFlags[FEATURE_FLAGS.SUBSCRIBE_TO_ALL_PRODUCTS] === 'test' ? 'Upgrade' : 'Subscribe'
    return (
        <OnboardingStep
            title="Plans"
            showSkip={!product.subscribed}
            stepKey={stepKey}
            continueOverride={
                product?.subscribed ? undefined : (
                    <BillingUpgradeCTA
                        // TODO: redirect path won't work properly until navigation is properly set up
                        to={getUpgradeProductLink({
                            product,
                            upgradeToPlanKey: plan.plan_key || '',
                            redirectPath,
                            includeAddons: true,
                            subscriptionLevel: billing?.subscription_level,
                            featureFlags,
                        })}
                        type="primary"
                        status="alt"
                        center
                        disableClientSideRouting
                        onClick={() => {
                            reportBillingUpgradeClicked(product.type)
                        }}
                        data-attr="onboarding-subscribe-button"
                    >
                        {action}
                    </BillingUpgradeCTA>
                )
            }
        >
            {billing?.products && productKey && product ? (
                <div className="mt-6">
                    {product.subscribed && (
                        <div className="mb-8">
                            <div className="bg-success-highlight rounded p-6 flex justify-between items-center">
                                <div className="flex gap-x-4">
                                    <IconCheckCircle className="text-success text-3xl mb-6" />
                                    <div>
                                        <h3 className="text-lg font-bold mb-1 text-left">{action} successful</h3>
                                        <p className="mx-0 mb-0">You're all ready to use {product.name}.</p>
                                    </div>
                                </div>
                                <div className="h-20">
                                    <StarHog className="h-full w-full" />
                                </div>
                            </div>
                            <LemonButton
                                data-attr="show-plans"
                                className="mt-2"
                                onClick={() => setShowPlanComp(!showPlanComp)}
                            >
                                {showPlanComp ? 'Hide' : 'Show'} plans
                            </LemonButton>
                            {currentPlan?.initial_billing_limit && (
                                <div className="mt-2">
                                    <LemonBanner type="info">
                                        To protect your costs and ours, this product has an initial billing limit of $
                                        {currentPlan.initial_billing_limit}. You can change or remove this limit on the
                                        Billing page.
                                    </LemonBanner>
                                </div>
                            )}
                        </div>
                    )}

                    {(!product.subscribed || showPlanComp) && (
                        <>
                            <BillingHero />
                            {featureFlags[FEATURE_FLAGS.SUBSCRIBE_TO_ALL_PRODUCTS] === 'test' ? (
                                <AllProductsPlanComparison product={product} />
                            ) : (
                                <PlanComparison product={product} />
                            )}
                        </>
                    )}
                </div>
            ) : (
                <Spinner className="text-lg" />
            )}
        </OnboardingStep>
    )
}
