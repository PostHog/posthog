import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'

import { ProductKey } from '~/queries/schema/schema-general'
import { BillingProductV2AddonType, BillingProductV2Type } from '~/types'

import { BillingAddonFeaturesList } from './BillingAddonFeaturesList'
import { billingLogic } from './billingLogic'

interface AddonFeatureLossNoticeProps {
    product: BillingProductV2Type | BillingProductV2AddonType
    targetProduct?: BillingProductV2Type | BillingProductV2AddonType
}

export const AddonFeatureLossNotice = ({ product, targetProduct }: AddonFeatureLossNoticeProps): JSX.Element | null => {
    const [isExpanded, setIsExpanded] = useState(false)
    const { billing } = useValues(billingLogic)

    const currentFeatures = product.features.filter((f) => !f.entitlement_only)
    const targetFeatures = (targetProduct?.features || []).filter((f) => !f.entitlement_only)

    // Fall back to base platform plan features if no target product
    const platformAndSupportProduct = billing?.products?.find((p) => p.type === ProductKey.PLATFORM_AND_SUPPORT)
    const currentPlatformPlan = platformAndSupportProduct?.plans?.find((plan) => plan.current_plan)
    const basePlatformFeatures = currentPlatformPlan?.features?.filter((f) => !f.entitlement_only) || []

    const featuresToKeep = targetProduct ? [...targetFeatures, ...basePlatformFeatures] : basePlatformFeatures
    const featuresToLose = currentFeatures.filter((feature) => !featuresToKeep.some((f) => f.key === feature.key))

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
