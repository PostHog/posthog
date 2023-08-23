import { SceneExport } from 'scenes/sceneTypes'
import { useValues } from 'kea'
import { useEffect } from 'react'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { onboardingLogic } from './onboardingLogic'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'
import { convertLargeNumberToWords } from 'scenes/billing/billing-utils'
import { BillingProductV2Type } from '~/types'

export const scene: SceneExport = {
    component: Onboarding,
    // logic: featureFlagsLogic,
}

const OnboardingProductIntro = ({ product }: { product: BillingProductV2Type }): JSX.Element => {
    const { currentAndUpgradePlans } = useValues(billingProductLogic({ product }))
    const upgradePlan = currentAndUpgradePlans?.upgradePlan
    return (
        <div className="flex flex-col w-full min-h-full p-6 bg-mid items-center justify-center">
            <div className="max-w-lg flex mb-8 items-center">
                <div className="w-1/2 pr-4">
                    <h1 className="text-5xl font-bold">{product.name}</h1>
                    <h2 className="font-bold">{product.description}</h2>
                    <p>
                        {upgradePlan?.tiers?.[0].unit_amount_usd &&
                            parseInt(upgradePlan?.tiers?.[0].unit_amount_usd) === 0 && (
                                <p className="ml-0 mb-0 mt-4">
                                    <span className="font-bold">
                                        First {convertLargeNumberToWords(upgradePlan?.tiers?.[0].up_to, null)}{' '}
                                        {product.unit}s free
                                    </span>
                                    , then <span className="font-bold">${upgradePlan?.tiers?.[1].unit_amount_usd}</span>
                                    <span className="text-muted">/{product.unit}</span>.{' '}
                                    <Link>
                                        <span className="font-bold text-brand-red">Volume discounts</span>
                                    </Link>{' '}
                                    after {convertLargeNumberToWords(upgradePlan?.tiers?.[1].up_to, null)}/mo.
                                </p>
                            )}
                    </p>
                    <div className="flex gap-x-2">
                        <LemonButton type="primary">Get started</LemonButton>
                        {product.docs_url && (
                            <LemonButton type="secondary" to={product.docs_url}>
                                Learn more
                            </LemonButton>
                        )}
                    </div>
                </div>
                <div className="shrink w-1/2">
                    <img
                        src="https://posthog.com/static/fa61e27ed8df786a6f6d309db72f757b/6a3c8/product-analytics.webp"
                        className="w-full"
                    />
                </div>
            </div>

            <div className="flex w-full max-w-xl justify-center gap-6 flex-wrap" />
        </div>
    )
}

export function Onboarding(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { product } = useValues(onboardingLogic)

    useEffect(() => {
        if (featureFlags[FEATURE_FLAGS.PRODUCT_SPECIFIC_ONBOARDING] !== 'test') {
            location.href = urls.ingestion()
        }
    }, [])

    return product ? <OnboardingProductIntro product={product} /> : null
}
