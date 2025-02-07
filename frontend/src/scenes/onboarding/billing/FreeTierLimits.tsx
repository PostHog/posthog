import * as Icons from '@posthog/icons'

import { availableOnboardingProducts } from '../onboardingLogic'

type FreeTierLimit = {
    title: string
    value: string
    icon: keyof typeof Icons
    color: string
}

const freeTierLimits: FreeTierLimit[] = [
    {
        title: 'Analytics',
        value: '1M events',
        icon: availableOnboardingProducts.product_analytics.icon,
        color: availableOnboardingProducts.product_analytics.iconColor,
    },
    {
        title: 'Session replay',
        value: '5K recordings',
        icon: availableOnboardingProducts.session_replay.icon,
        color: availableOnboardingProducts.session_replay.iconColor,
    },
    {
        title: 'Feature flags',
        value: '1M requests',
        icon: availableOnboardingProducts.feature_flags.icon,
        color: availableOnboardingProducts.feature_flags.iconColor,
    },
    {
        title: 'Experiments',
        value: 'Billed with feature flags',
        icon: availableOnboardingProducts.experiments.icon,
        color: availableOnboardingProducts.experiments.iconColor,
    },
    {
        title: 'Surveys',
        value: '250 responses',
        icon: availableOnboardingProducts.surveys.icon,
        color: availableOnboardingProducts.surveys.iconColor,
    },
    {
        title: 'Data warehouse',
        value: '1M synced rows',
        icon: availableOnboardingProducts.data_warehouse.icon,
        color: availableOnboardingProducts.data_warehouse.iconColor,
    },
]

const FreeTierItem = ({ limit }: { limit: FreeTierLimit }): JSX.Element => {
    const Icon = Icons[limit.icon]
    return (
        <div className="flex flex-col items-center w-36">
            <div className="flex gap-1 items-center">
                <Icon className="w-6 h-6" color={limit.color} />
            </div>
            <strong className="text-[15px] text-center leading-none mt-2 mb-1">{limit.title}</strong>
            <div className="text-sm text-center text-success dark:text-green-400">{limit.value}</div>
        </div>
    )
}

export const FreeTierLimits: React.FC = (): JSX.Element => {
    return (
        <div className="mt-12">
            <h4 className="text-center text-base font-semibold text-gray-800 dark:text-gray-100 mb-4">
                Monthly free tier applies to both plans
            </h4>
            <div className="flex justify-center">
                <div className="grid grid-cols-3 gap-4">
                    {freeTierLimits.map((limit, index) => (
                        <FreeTierItem key={index} limit={limit} />
                    ))}
                </div>
            </div>
        </div>
    )
}
