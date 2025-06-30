import { IconCheckCircle, IconX } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { BillingFeatureType } from '~/types'

interface BillingAddonFeaturesListProps {
    addonFeatures?: BillingFeatureType[]
    addonType: string
    /** Controls whether features are shown as included (checkmark) or removed (red X) */
    variant?: 'included' | 'removed'
}

export const BillingAddonFeaturesList = ({
    addonFeatures,
    addonType,
    variant = 'included',
}: BillingAddonFeaturesListProps): JSX.Element | null => {
    if (!addonFeatures || addonFeatures.length <= 2) {
        return null
    }

    const icon =
        variant === 'included' ? <IconCheckCircle className="text-success" /> : <IconX className="text-danger" />

    const title = variant === 'included' ? 'Features included:' : 'Features to lose:'

    return (
        <div>
            <p className="ml-0 mb-2 max-w-200">{title}</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4">
                {addonFeatures.map((feature, index) => (
                    <div className="flex gap-x-2 items-center mb-2" key={'addon-features-' + addonType + index}>
                        {icon}
                        <Tooltip key={feature.key} title={feature.description}>
                            <b>
                                {feature.name}
                                {feature.note ? ': ' + feature.note : ''}
                                {feature.limit && feature.unit ? ': ' + feature.limit + ' ' + feature.unit : ''}
                            </b>
                        </Tooltip>
                    </div>
                ))}
            </div>
        </div>
    )
}
