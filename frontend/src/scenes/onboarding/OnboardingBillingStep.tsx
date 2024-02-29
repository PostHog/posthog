import { LemonBanner, LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { StarHog } from 'lib/components/hedgehogs'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconCheckCircleOutline } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useState } from 'react'
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
    const { billing, redirectPath } = useValues(billingLogic)
    const { productKey } = useValues(onboardingLogic)
    const { currentAndUpgradePlans } = useValues(billingProductLogic({ product }))
    const { reportBillingUpgradeClicked } = useActions(eventUsageLogic)
    const plan = currentAndUpgradePlans?.upgradePlan
    const currentPlan = currentAndUpgradePlans?.currentPlan
    const { featureFlags } = useValues(featureFlagLogic)

    const [showPlanComp, setShowPlanComp] = useState(false)

    return (
        <OnboardingStep
            title="Plans"
            showSkip={!product.subscribed}
            stepKey={stepKey}
            continueOverride={
                product?.subscribed ? undefined : (
                    <LemonButton
                        // TODO: redirect path won't work properly until navigation is properly set up
                        to={getUpgradeProductLink(product, plan.plan_key || '', redirectPath, true)}
                        type="primary"
                        status="alt"
                        center
                        disableClientSideRouting
                        onClick={() => {
                            reportBillingUpgradeClicked(product.type)
                        }}
                    >
                        {featureFlags[FEATURE_FLAGS.BILLING_UPGRADE_LANGUAGE] === 'subscribe'
                            ? 'Subscribe to paid plan'
                            : featureFlags[FEATURE_FLAGS.BILLING_UPGRADE_LANGUAGE] === 'credit_card' &&
                              !billing?.has_active_subscription
                            ? 'Add credit card to get paid features'
                            : featureFlags[FEATURE_FLAGS.BILLING_UPGRADE_LANGUAGE] === 'credit_card' &&
                              billing?.has_active_subscription
                            ? 'Add paid plan'
                            : 'Upgrade to paid plan'}
                    </LemonButton>
                )
            }
        >
            {billing?.products && productKey && product ? (
                <div className="mt-6">
                    {product.subscribed && (
                        <div className="mb-8">
                            <div className="bg-success-highlight rounded p-6 flex justify-between items-center">
                                <div className="flex gap-x-4">
                                    <IconCheckCircleOutline className="text-success text-3xl mb-6" />
                                    <div>
                                        <h3 className="text-lg font-bold mb-1 text-left">
                                            {featureFlags[FEATURE_FLAGS.BILLING_UPGRADE_LANGUAGE] === 'subscribe'
                                                ? 'Subscribe successful'
                                                : featureFlags[FEATURE_FLAGS.BILLING_UPGRADE_LANGUAGE] ===
                                                      'credit_card' && !billing?.has_active_subscription
                                                ? 'Successfully added credit card'
                                                : featureFlags[FEATURE_FLAGS.BILLING_UPGRADE_LANGUAGE] ===
                                                      'credit_card' && !billing?.has_active_subscription
                                                ? 'Successfully added paid plan'
                                                : 'Upgrade successful'}
                                        </h3>
                                        <p className="mx-0 mb-0">You're all ready to use {product.name}.</p>
                                    </div>
                                </div>
                                <div className="h-20">
                                    <StarHog className="h-full w-full" />
                                </div>
                            </div>
                            <LemonButton className="mt-2" onClick={() => setShowPlanComp(!showPlanComp)}>
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
