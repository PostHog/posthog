import { useValues } from 'kea'
import { useEffect } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { SupermanHog } from 'lib/components/hedgehogs'
import { billingLogic } from 'scenes/billing/billingLogic'

import type { BillingProductV2Type, OnboardingStepKey } from '~/types'

import { OnboardingStep } from '../OnboardingStep'
import PlanCards from './PlanCards'

type Props = {
    product: BillingProductV2Type
    stepKey: OnboardingStepKey
}

export const OnboardingUpgradeStep = ({ product, stepKey }: Props): JSX.Element => {
    const { billingLoading } = useValues(billingLogic)

    if (billingLoading) {
        return (
            <div className="my-20 flex items-center justify-center">
                <Spinner className="text-muted h-10 w-10 text-2xl" />
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
            {product.subscribed && <ProductSubscribed product={product} />}
        </OnboardingStep>
    )
}

const ProductSubscribed = ({ product }: { product: BillingProductV2Type }): JSX.Element => {
    const { trigger, HogfettiComponent } = useHogfetti({ count: 100, duration: 3000 })

    useEffect(() => {
        const run = async (): Promise<void> => {
            trigger()
            await new Promise((resolve) => setTimeout(resolve, 1000))
            trigger()
            await new Promise((resolve) => setTimeout(resolve, 1000))
            trigger()
        }

        void run()
    }, [trigger])

    return (
        <div className="relative flex flex-col items-center text-center">
            <HogfettiComponent />

            {/* Superman Hog floating animation */}
            <div className="animate-float h-40 w-40">
                <SupermanHog className="h-full w-full object-contain" />
            </div>

            {/* Text Below */}
            <h3 className="mt-6 text-2xl font-bold">Go forth and build amazing products!</h3>
            <p className="text-gray-700">
                You've unlocked all features for <strong>{product.name}</strong>.
            </p>
        </div>
    )
}
