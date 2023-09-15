import { OnboardingStep } from './OnboardingStep'
import { PlanComparison } from 'scenes/billing/PlanComparison'
import { useValues } from 'kea'
import { billingLogic } from 'scenes/billing/billingLogic'
import { onboardingLogic } from './onboardingLogic'
import { useEffect, useState } from 'react'
import { BillingProductV2Type } from '~/types'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { BillingHero } from 'scenes/billing/BillingHero'

export const OnboardingBillingStep = (): JSX.Element => {
    const { billing } = useValues(billingLogic)
    const { productKey } = useValues(onboardingLogic)
    const [product, setProduct] = useState<BillingProductV2Type | null>(null)

    useEffect(() => {
        setProduct(billing?.products?.find((p) => p.type === productKey) || null)
    }, [billing, productKey])

    return (
        <OnboardingStep title="Add credit card details" showSkip>
            <BillingHero />
            {billing?.products && productKey && product ? (
                <div className="mt-6">
                    <PlanComparison product={product} />
                </div>
            ) : (
                <Spinner className="text-lg" />
            )}
        </OnboardingStep>
    )
}
