import { LemonBanner, LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { StarHog } from 'lib/components/hedgehogs'
import { IconCheckCircleOutline } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { getUpgradeProductLink } from 'scenes/billing/billing-utils'
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

    const ChoosePlanButton = ({
        planKey,
        currentPlan,
        isFreePlan,
    }: {
        planKey: string | undefined
        currentPlan: boolean
        isFreePlan: boolean
    }): JSX.Element => {
        return (
            <LemonButton
                to={getUpgradeProductLink(product, planKey || '', redirectPath, true)}
                type={isFreePlan ? 'secondary' : 'primary'}
                status={currentPlan ? 'default' : 'alt'}
                fullWidth
                center
                disableClientSideRouting
                onClick={() => {
                    if (!currentPlan) {
                        reportBillingUpgradeClicked(product.type)
                    }
                }}
            >
                Choose Plan {currentPlan && '(Current Plan)'}
            </LemonButton>
        )
    }
    // const upgradeButtons = product.plans?.map((plan) => {
    //     return (
    //             {!plan.current_plan && product.addons?.length > 0 && (
    //                 <p className="text-center ml-0 mt-2 mb-0">
    //                     <Link
    //                         to={`/api/billing-v2/activation?products=${product.type}:${plan.plan_key}&redirect_path=${redirectPath}`}
    //                         className="text-muted text-xs"
    //                         disableClientSideRouting
    //                     >
    //                         or upgrade without addons
    //                     </Link>
    //                 </p>
    //             )}
    //     )
    // })

    const formatCompactNumber = (number: number): string => {
        const formatter = Intl.NumberFormat('en', {
            notation: 'compact',
            compactDisplay: number < 999999 ? 'short' : 'long',
        })
        return formatter.format(number).toLowerCase()
    }

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
                        Subscribe to Paid Plan
                    </LemonButton>
                )
            }
        >
            <h3>Pick a Plan</h3>
            <LemonDivider />
            <div className="flex justify-between gap-8">
                {product.plans.map((plan) => {
                    const isFreePlan = (plan.free_allocation && !plan.tiers) as boolean
                    const formattedUnit = plan.unit![0].toUpperCase() + plan.unit?.substring(1) + 's'
                    const dataRetentionFeature = plan.features.find((feature) => feature.key.includes('data_retention'))
                    const dataRetentionFormatted = `${dataRetentionFeature?.limit} ${dataRetentionFeature?.unit}`
                    const priceTierFree = `First ${formatCompactNumber(plan.tiers?.[0].up_to)} ${plan.unit}s/mo free`
                    const priceTierPaid = `Then ${parseFloat(plan.tiers?.[1]?.unit_amount_usd || '')}/${plan.unit}`
                    return (
                        <div className="PlanUpgradeCard" key={plan.plan_key}>
                            <h3 className="mb-0">{isFreePlan ? 'Free' : 'Paid'}</h3>
                            <h4 className="mb-6">
                                {isFreePlan ? 'No credit card required' : 'All features, no limitations'}
                            </h4>
                            <div className="PlanUpgradeCard__Item">
                                <p>{formattedUnit}</p>
                                <p className="font-bold">{plan.free_allocation || 'Unlimited'}</p>
                            </div>
                            <div className="PlanUpgradeCard__Item">
                                <p>Data Retention</p>
                                <p className="font-bold">{dataRetentionFormatted}</p>
                            </div>
                            <div className="PlanUpgradeCard__Item">
                                <p>Features</p>
                                <p className="font-bold">
                                    {isFreePlan ? 'Basic features' : 'All features (see below)'}
                                </p>
                            </div>
                            <div className="PlanUpgradeCard__Item">
                                <p>Price</p>
                                <div>
                                    <p className="font-bold mb-0">{isFreePlan ? 'Free' : priceTierFree}</p>
                                    {!isFreePlan && <p>{priceTierPaid}</p>}
                                </div>
                            </div>
                            <ChoosePlanButton
                                planKey={plan.plan_key}
                                currentPlan={plan.current_plan}
                                isFreePlan={isFreePlan}
                            />
                        </div>
                    )
                })}
            </div>
            {billing?.products && productKey && product ? (
                <div className="mt-6">
                    {product.subscribed ? (
                        <div className="mb-8">
                            <div className="bg-success-highlight rounded p-6 flex justify-between items-center">
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
                    ) : (
                        <>
                            <h3>Compare Plans for {product.name}</h3>
                            <LemonDivider />
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
