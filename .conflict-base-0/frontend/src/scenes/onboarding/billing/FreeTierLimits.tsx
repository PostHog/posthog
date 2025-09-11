import { useValues } from 'kea'

import * as Icons from '@posthog/icons'

import { billingLogic } from 'scenes/billing/billingLogic'

import { availableOnboardingProducts } from '../utils'

type FreeTierLimit = {
    title: string
    icon: string
    color: string
    unit: string
    value: number
}

const formatFreeTierLimit = (value: number): string => {
    return Intl.NumberFormat('en', {
        notation: 'compact',
        compactDisplay: 'short',
        maximumFractionDigits: 1,
    }).format(value)
}

const FreeTierItem = ({ limit }: { limit: FreeTierLimit }): JSX.Element => {
    const Icon = Icons[limit.icon as keyof typeof Icons]
    return (
        <div className="flex flex-col items-center w-36">
            <div className="flex gap-1 items-center">
                <Icon className="w-6 h-6" color={limit.color} />
            </div>
            <strong className="text-[15px] text-center leading-none mt-2 mb-1">{limit.title}</strong>
            <div className="text-sm text-center text-success dark:text-green-400">
                {`${formatFreeTierLimit(limit.value)} ${limit.unit}${limit.value === 1 ? '' : 's'}`}
            </div>
        </div>
    )
}

export const FreeTierLimits: React.FC = (): JSX.Element => {
    const { billing } = useValues(billingLogic)

    const availableProducts = billing?.products?.filter((p) => p.type in availableOnboardingProducts)

    const freeTierLimits = (availableProducts ?? [])
        .map((p) => {
            const freePlan = p.plans.find((plan) => plan.plan_key?.startsWith('free'))
            return {
                title: p.name,
                icon:
                    p.icon_key ?? availableOnboardingProducts[p.type as keyof typeof availableOnboardingProducts]?.icon,

                color: availableOnboardingProducts[p.type as keyof typeof availableOnboardingProducts]?.iconColor,
                unit: freePlan?.unit ?? '',
                value: freePlan?.free_allocation ?? 0,
            }
        })
        .filter((limit) => limit.unit && limit.value > 0)

    return (
        <div className="mt-12">
            <h4 className="text-center text-base font-semibold text-gray-800 dark:text-gray-100 mb-4">
                Monthly free tier applies to both plans
            </h4>
            <div className="flex justify-center">
                <div className="flex flex-wrap justify-center">
                    {freeTierLimits.map((limit) => (
                        <div key={limit.title} className="w-full basis-1/3 py-2 flex justify-center items-center">
                            <FreeTierItem limit={limit} />
                        </div>
                    ))}
                </div>
            </div>
        </div>
    )
}
