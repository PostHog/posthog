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
            <p className="max-w-200 mb-2 ml-0">{title}</p>
            <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
                {addonFeatures.map((feature, index) => (
                    <div className="mb-2 flex items-center gap-x-2" key={'addon-features-' + addonType + index}>
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
