import { LemonBanner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import posthog from 'posthog-js'
import { useState } from 'react'

import { BillingProductV2AddonType, BillingProductV2Type, ProductKey } from '~/types'

import { BillingAddonFeaturesList } from './BillingAddonFeaturesList'
import { billingLogic } from './billingLogic'

interface FeatureLossNoticeProps {
    product: BillingProductV2Type | BillingProductV2AddonType
    isPlaformAndSupportProduct: boolean
}

export const FeatureLossNotice = ({
    product,
    isPlaformAndSupportProduct,
}: FeatureLossNoticeProps): JSX.Element | null => {
    const [isExpanded, setIsExpanded] = useState(false)
    const { billing } = useValues(billingLogic)

    if (!isPlaformAndSupportProduct) {
        return null
    }

    const platformAndSupportProduct = billing?.products?.find((p) => p.type === ProductKey.PLATFORM_AND_SUPPORT)
    const currentPlatformPlan = platformAndSupportProduct?.plans?.find((plan) => plan.current_plan)
    const addonFeatures = product.features?.filter((feature) => !feature.entitlement_only) || []
    const currentPlanFeatures = currentPlatformPlan?.features?.filter((feature) => !feature.entitlement_only) || []
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
        <LemonBanner type="warning">
            <div>
                <div className="flex items-center gap-2 cursor-pointer font-semibold" onClick={handleToggle}>
                    You'll lose access to {featuresToLose.length} features, click here to find out which ones.
                </div>
                <AnimatedCollapsible collapsed={!isExpanded}>
                    <div className="mt-3">
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
