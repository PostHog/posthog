import { LemonButton } from '@posthog/lemon-ui'
import { IconBarChart } from 'lib/lemon-ui/icons'
import { SceneExport } from 'scenes/sceneTypes'
import { BillingProductV2Type, ProductKey } from '~/types'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { useEffect } from 'react'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'
import { billingLogic } from 'scenes/billing/billingLogic'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { LemonCard } from 'lib/lemon-ui/LemonCard/LemonCard'
import { router } from 'kea-router'
import { getProductUri } from 'scenes/onboarding/onboardingLogic'
import { productsLogic } from './productsLogic'

export const scene: SceneExport = {
    component: Products,
    logic: productsLogic,
}

function OnboardingCompletedButton({
    productUrl,
    onboardingUrl,
    productKey,
}: {
    productUrl: string
    onboardingUrl: string
    productKey: ProductKey
}): JSX.Element {
    const { onSelectProduct } = useActions(productsLogic)
    return (
        <>
            <LemonButton type="secondary" status="muted" to={productUrl}>
                Go to product
            </LemonButton>
            <LemonButton
                type="tertiary"
                status="muted"
                onClick={() => {
                    onSelectProduct(productKey)
                    router.actions.push(onboardingUrl)
                }}
            >
                Set up again
            </LemonButton>
        </>
    )
}

function OnboardingNotCompletedButton({ url, productKey }: { url: string; productKey: ProductKey }): JSX.Element {
    const { onSelectProduct } = useActions(productsLogic)
    return (
        <LemonButton
            type="primary"
            onClick={() => {
                onSelectProduct(productKey)
                router.actions.push(url)
            }}
        >
            Get started
        </LemonButton>
    )
}

function ProductCard({ product }: { product: BillingProductV2Type }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const onboardingCompleted = currentTeam?.has_completed_onboarding_for?.[product.type]
    return (
        <LemonCard className={`max-w-80 flex flex-col`} key={product.type}>
            <div className="flex mb-2">
                <div className="bg-mid rounded p-2 flex">
                    {product.image_url ? (
                        <img className="w-6 h-6" alt={`Logo for PostHog ${product.name}`} src={product.image_url} />
                    ) : (
                        <IconBarChart className="w-6 h-6" />
                    )}
                </div>
            </div>
            <div className="mb-2">
                <h3 className="bold mb-0">{product.name}</h3>
            </div>
            <p className="grow">{product.description}</p>
            <div className="flex gap-x-2">
                {onboardingCompleted ? (
                    <OnboardingCompletedButton
                        productUrl={getProductUri(product.type as ProductKey)}
                        onboardingUrl={urls.onboarding(product.type)}
                        productKey={product.type as ProductKey}
                    />
                ) : (
                    <OnboardingNotCompletedButton
                        url={urls.onboarding(product.type)}
                        productKey={product.type as ProductKey}
                    />
                )}
            </div>
        </LemonCard>
    )
}

export function Products(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { billing } = useValues(billingLogic)
    const { currentTeam } = useValues(teamLogic)
    const isFirstProduct = Object.keys(currentTeam?.has_completed_onboarding_for || {}).length === 0
    const products = billing?.products || []

    useEffect(() => {
        if (featureFlags[FEATURE_FLAGS.PRODUCT_SPECIFIC_ONBOARDING] !== 'test') {
            location.href = urls.ingestion()
        }
    }, [])

    return (
        <div className="flex flex-col w-full h-full p-6 items-center justify-center bg-mid">
            <div className="mb-8">
                <h1 className="text-center text-4xl">Pick your {isFirstProduct ? 'first' : 'next'} product.</h1>
                <p className="text-center">
                    Pick your {isFirstProduct ? 'first' : 'next'} product to get started with. You can set up any others
                    you'd like later.
                </p>
            </div>
            {products.length > 0 ? (
                <>
                    <div className="flex w-full max-w-xl justify-center gap-6 flex-wrap">
                        {products
                            .filter((product) => !product.contact_support && !product.inclusion_only)
                            .map((product) => (
                                <ProductCard product={product} key={product.type} />
                            ))}
                    </div>
                </>
            ) : (
                <Spinner className="text-3xl" />
            )}
        </div>
    )
}
