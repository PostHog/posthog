import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'

import { BillingProductV2AddonType, BillingProductV2Type, ProductKey } from '~/types'

import { BillingAddonFeaturesList } from './BillingAddonFeaturesList'
import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'

interface AddonFeatureLossNoticeProps {
    product: BillingProductV2Type | BillingProductV2AddonType
}

export const AddonFeatureLossNotice = ({ product }: AddonFeatureLossNoticeProps): JSX.Element | null => {
    const [isExpanded, setIsExpanded] = useState(false)
    const { billing } = useValues(billingLogic)

    const { currentAndUpgradePlans } = useValues(billingProductLogic({ product }))
    const addonFeatures = (
        currentAndUpgradePlans?.upgradePlan?.features ||
        currentAndUpgradePlans?.currentPlan?.features ||
        product.features ||
        []
    ).filter((f) => !f.entitlement_only)

    // Current base platform and support plan and features
    const platformAndSupportProduct = billing?.products?.find((p) => p.type === ProductKey.PLATFORM_AND_SUPPORT)
    const currentPlatformPlan = platformAndSupportProduct?.plans?.find((plan) => plan.current_plan)
    // TODO: instead of assuming they are moving to paid, support the move from one addon to another (e.g. from scale to boost)
    const currentPlanFeatures = currentPlatformPlan?.features?.filter((feature) => !feature.entitlement_only) || []

    // Difference between addon plan and the plan they are moving to
    const featuresToLose = addonFeatures.filter(
        (addonFeature) => !currentPlanFeatures.some((planFeature) => planFeature.key === addonFeature.key)
    )

    if (!featuresToLose?.length) {
        return null
    }

    const handleToggle = (): void => {
        const newExpandedState = !isExpanded
        setIsExpanded(newExpandedState)

        if (newExpandedState) {
            posthog.capture('billing_unsubscribe_feature_list_expanded', {
                product_type: product.type,
                feature_count: featuresToLose.length,
            })
        }
    }

    return (
        <LemonBanner type="warning" hideIcon className="p-3">
            <div>
                <div className="flex items-center gap-2 cursor-pointer font-semibold" onClick={handleToggle}>
                    You'll lose access to {featuresToLose.length} features, click here to find out which ones.
                </div>
                <AnimatedCollapsible collapsed={!isExpanded}>
                    <div className="pt-3 pb-1">
                        <BillingAddonFeaturesList
                            addonFeatures={featuresToLose}
                            addonType={product.type}
                            variant="removed"
                        />
                    </div>
                </AnimatedCollapsible>
            </div>
        </LemonBanner>
    )
}
