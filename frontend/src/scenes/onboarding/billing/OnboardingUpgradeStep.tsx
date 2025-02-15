import { IconCheckCircle } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { StarHog } from 'lib/components/hedgehogs'
import { billingLogic } from 'scenes/billing/billingLogic'

import type { BillingProductV2Type } from '~/types'

import { OnboardingStepKey } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'
import PlanCards from './PlanCards'

type Props = {
    product: BillingProductV2Type
    stepKey: OnboardingStepKey
}

export const OnboardingUpgradeStep = ({ product, stepKey }: Props): JSX.Element => {
    const { billing, billingLoading } = useValues(billingLogic)

    const action = billing?.subscription_level === 'custom' ? 'Subscribe' : 'Upgrade'

    if (billingLoading) {
        return (
            <div className="flex items-center justify-center my-20">
                <Spinner className="text-2xl text-muted w-10 h-10" />
            </div>
        )
    }

    return (
        <OnboardingStep
            title="Select a plan"
            stepKey={stepKey}
            continueOverride={!product.subscribed ? <></> : undefined}
        >
            {!product.subscribed && <PlanCards product={product} />}
            {product.subscribed && <ProductSubscribed product={product} action={action} />}
        </OnboardingStep>
    )
}

const ProductSubscribed = ({ product, action }: { product: BillingProductV2Type; action: string }): JSX.Element => {
    return (
        <div className="mb-8">
            <div className="bg-success-highlight rounded p-6 flex justify-between items-center">
                <div className="flex gap-x-4 min-w-0 justify-center items-center">
                    <IconCheckCircle className="text-success text-3xl flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                        <h3 className="text-lg font-bold mb-1 text-left">{action} successful</h3>
                        <p className="mx-0 mb-0">You're all ready to use {product.name}.</p>
                    </div>
                </div>
                <div className="h-20 w-20 flex-shrink-0">
                    <StarHog className="h-full w-full object-contain" />
                </div>
            </div>
        </div>
    )
}
