import { LemonBanner } from '@posthog/lemon-ui'
import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import posthog from 'posthog-js'
import { useState } from 'react'

import { BillingProductV2AddonType, BillingProductV2Type } from '~/types'

import { BillingAddonFeaturesList } from './BillingAddonFeaturesList'

interface FeatureLossNoticeProps {
    product: BillingProductV2Type | BillingProductV2AddonType
    isPlaformAndSupportProduct: boolean
}

export const FeatureLossNotice = ({
    product,
    isPlaformAndSupportProduct,
}: FeatureLossNoticeProps): JSX.Element | null => {
    const [isExpanded, setIsExpanded] = useState(false)
    const featuresToLose = product.features?.filter((feature) => !feature.entitlement_only)

    if (!isPlaformAndSupportProduct || !featuresToLose?.length) {
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
