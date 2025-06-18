import { LemonCollapse, Tooltip } from '@posthog/lemon-ui'
import posthog from 'posthog-js'

import { BillingFeatureType, BillingProductV2AddonType, BillingProductV2Type } from '~/types'

interface FeatureLossNoticeProps {
    product: BillingProductV2Type | BillingProductV2AddonType
    isPlaformAndSupportProduct: boolean
}

interface FeatureCategoryListProps {
    groupedFeatures: Record<string, BillingFeatureType[]>
}

const FeatureCategoryList = ({ groupedFeatures }: FeatureCategoryListProps): JSX.Element => {
    return (
        <div className="space-y-3">
            {Object.entries(groupedFeatures)
                .sort(([categoryA], [categoryB]) => {
                    if (categoryA === 'Other Features') {
                        return 1
                    }
                    if (categoryB === 'Other Features') {
                        return -1
                    }
                    return categoryA.localeCompare(categoryB)
                })
                .map(([category, features]) => (
                    <div key={category}>
                        <h5 className="text-xs font-semibold uppercase text-secondary mb-1">{category}</h5>
                        <div className="space-y-1">
                            {features.map((feature) => (
                                <div key={feature.key} className="text-xs">
                                    <span className="font-medium">{feature.name}</span>
                                    {feature.description && (
                                        <span className="text-secondary ml-1">- {feature.description}</span>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>
                ))}
        </div>
    )
}

export const FeatureLossNotice = ({
    product,
    isPlaformAndSupportProduct,
}: FeatureLossNoticeProps): JSX.Element | null => {
    const featuresToLose = product.features?.filter((feature) => !feature.entitlement_only)

    if (!isPlaformAndSupportProduct || !featuresToLose?.length) {
        return null
    }

    const groupedFeatures = featuresToLose.reduce((groups, feature) => {
        const category = feature.category || 'Other Features'

        if (!groups[category]) {
            groups[category] = []
        }
        groups[category].push(feature)
        return groups
    }, {} as Record<string, BillingFeatureType[]>)

    // Get 5 randomly selected features to show in summary
    const shuffledFeatures = [...featuresToLose].sort(() => Math.random() - 0.5)
    const keyFeatures = shuffledFeatures.slice(0, Math.min(5, featuresToLose.length))
    const totalFeatureCount = featuresToLose.length

    const handleFeatureListToggle = (activeKey: string | null): void => {
        if (activeKey === 'all-features') {
            posthog.capture('billing_unsubscribe_feature_list_expanded', {
                product_type: product.type,
                feature_count: totalFeatureCount,
            })
        }
    }

    return (
        <div className="bg-warning-highlight border border-warning rounded p-4 mb-4">
            <div className="flex items-start gap-2 mb-3">
                <span className="text-warning-dark font-medium text-sm">⚠️</span>
                <div className="flex-1">
                    <h4 className="text-sm font-semibold mb-2 text-warning-dark">
                        You'll lose access to these features:
                    </h4>
                    <div className="space-y-1">
                        {keyFeatures.map((feature) => (
                            <div key={feature.key} className="text-xs">
                                {feature.description ? (
                                    <Tooltip title={feature.description}>
                                        <span className="font-medium cursor-help underline decoration-dotted underline-offset-2">
                                            {feature.name}
                                        </span>
                                    </Tooltip>
                                ) : (
                                    <span className="font-medium">{feature.name}</span>
                                )}
                            </div>
                        ))}
                    </div>
                    {totalFeatureCount > 5 && (
                        <div className="text-secondary text-xs">+ {totalFeatureCount - 5} more features</div>
                    )}
                </div>
            </div>

            <LemonCollapse
                panels={[
                    {
                        key: 'all-features',
                        header: 'View all features',
                        content: <FeatureCategoryList groupedFeatures={groupedFeatures} />,
                    },
                ]}
                size="small"
                onChange={handleFeatureListToggle}
            />
        </div>
    )
}
