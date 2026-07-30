import { IconCheck } from '@posthog/icons'

import { pluralize } from 'lib/utils/strings'
import { compact } from 'scenes/onboarding/self-driving/utils'
import { availableOnboardingProducts } from 'scenes/onboarding/shared/utils'

import { type BillingProductV2Type } from '~/types'

/**
 * Monthly free allowance on the tools the wizard turns on, so the plan reads as the whole platform
 * rather than PRs alone. It sits under both plans because subscribing changes nothing about it:
 * every tool keeps the same free tier either way.
 */
export function ToolFreeTiers({ products }: { products: BillingProductV2Type[] | undefined }): JSX.Element | null {
    const allowances = (products ?? [])
        .filter((product) => product.type in availableOnboardingProducts)
        .map((product) => {
            const freePlan = product.plans.find((plan) => plan.plan_key?.startsWith('free'))
            return { name: product.name, unit: freePlan?.unit ?? '', value: freePlan?.free_allocation ?? 0 }
        })
        .filter((allowance) => allowance.unit && allowance.value > 0)

    if (allowances.length === 0) {
        return null
    }

    return (
        <div className="w-full flex flex-col gap-2">
            <p className="m-0 text-xs text-muted">Every other tool keeps its free tier on both plans:</p>
            <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 m-0 p-0 list-none">
                {allowances.map(({ name, unit, value }) => (
                    <li key={name} className="flex items-center gap-2">
                        <IconCheck className="size-3.5 text-success shrink-0" />
                        <span className="text-xs text-muted">
                            <strong className="font-semibold text-default">{name}</strong>: {compact(value)}{' '}
                            {pluralize(value, unit, undefined, false)} a month
                        </span>
                    </li>
                ))}
            </ul>
        </div>
    )
}
