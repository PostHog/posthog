import { IconCheckCircle } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { BillingUpgradeCTA } from 'lib/components/BillingUpgradeCTA'
import { StarHog } from 'lib/components/hedgehogs'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useState } from 'react'
import { AllProductsPlanComparison } from 'scenes/billing/AllProductsPlanComparison'
import { getUpgradeProductLink } from 'scenes/billing/billing-utils'
import { BillingHero } from 'scenes/billing/BillingHero'
import { billingLogic } from 'scenes/billing/billingLogic'
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
    const { billing, redirectPath, billingLoading } = useValues(billingLogic)
    const { productKey } = useValues(onboardingLogic)
    const { reportBillingUpgradeClicked } = useActions(eventUsageLogic)

    const [showPlanComp, setShowPlanComp] = useState(false)

    const action = billing?.subscription_level === 'custom' ? 'Subscribe' : 'Upgrade'
    return (
        <OnboardingStep
            title="Plans"
            showSkip={!product.subscribed}
            stepKey={stepKey}
            continueOverride={
                product?.subscribed && !billingLoading ? undefined : (
                    <BillingUpgradeCTA
                        // TODO: redirect path won't work properly until navigation is properly set up
                        to={getUpgradeProductLink({
                            product,
                            redirectPath,
                            includeAddons: true,
                        })}
                        type="primary"
                        status="alt"
                        center
                        disabledReason={billingLoading && 'Please wait...'}
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
            {billing?.products && productKey && product && !billingLoading ? (
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
                        </div>
                    )}

                    {(!product.subscribed || showPlanComp) && (
                        <>
                            <BillingHero />
                            {billing?.subscription_level === 'custom' ? (
                                <PlanComparison product={product} />
                            ) : (
                                <AllProductsPlanComparison product={product} />
                            )}
                        </>
                    )}
                </div>
            ) : (
                <div className="flex items-center justify-center my-20">
                    <Spinner className="text-2xl text-muted w-10 h-10" />
                </div>
            )}
        </OnboardingStep>
    )
}
