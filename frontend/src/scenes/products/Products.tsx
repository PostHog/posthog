import { LemonButton } from '@posthog/lemon-ui'
import { SceneExport } from 'scenes/sceneTypes'
import { BillingProductV2Type, ProductKey } from '~/types'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { billingLogic } from 'scenes/billing/billingLogic'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { LemonCard } from 'lib/lemon-ui/LemonCard/LemonCard'
import { router } from 'kea-router'
import { getProductUri } from 'scenes/onboarding/onboardingLogic'
import { productsLogic } from './productsLogic'
import * as Icons from '@posthog/icons'

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

function OnboardingNotCompletedButton({
    url,
    productKey,
    getStartedActionOverride,
}: {
    url: string
    productKey: ProductKey
    getStartedActionOverride?: () => void
}): JSX.Element {
    const { onSelectProduct } = useActions(productsLogic)
    return (
        <LemonButton
            type="primary"
            onClick={() => {
                if (getStartedActionOverride) {
                    getStartedActionOverride()
                } else {
                    onSelectProduct(productKey)
                    router.actions.push(url)
                }
            }}
        >
            Get started
        </LemonButton>
    )
}

export function getProductIcon(iconKey?: string | null, className?: string): JSX.Element {
    return Icons[iconKey || 'IconLogomark']({ className })
}

export function ProductCard({
    product,
    getStartedActionOverride,
    orientation = 'vertical',
    className,
}: {
    product: BillingProductV2Type
    getStartedActionOverride?: () => void
    orientation?: 'horizontal' | 'vertical'
    className?: string
}): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const onboardingCompleted = currentTeam?.has_completed_onboarding_for?.[product.type]
    const vertical = orientation === 'vertical'

    return (
        <LemonCard
            className={`flex gap-x-4 gap-y-4 ${vertical ? 'flex-col max-w-80' : 'items-center'} ${className}`}
            key={product.type}
        >
            <div className="flex">
                <div>
                    <div className="bg-mid rounded p-2">{getProductIcon(product.icon_key, 'text-2xl')}</div>
                </div>
            </div>
            <div>
                <h3 className={`bold ${vertical ? 'mb-2' : 'mb-0'}`}>{product.name}</h3>
                <p className="grow m-0">{product.description}</p>
            </div>
            <div className={`flex gap-x-2 grow shrink-0 ${!vertical && 'justify-end'}`}>
                {onboardingCompleted ? (
                    <OnboardingCompletedButton
                        productUrl={getProductUri(product.type as ProductKey)}
                        onboardingUrl={urls.onboarding(product.type)}
                        productKey={product.type as ProductKey}
                    />
                ) : (
                    <div>
                        <OnboardingNotCompletedButton
                            url={urls.onboarding(product.type)}
                            productKey={product.type as ProductKey}
                            getStartedActionOverride={getStartedActionOverride}
                        />
                    </div>
                )}
            </div>
        </LemonCard>
    )
}

export function Products(): JSX.Element {
    const { billing } = useValues(billingLogic)
    const { currentTeam } = useValues(teamLogic)
    const isFirstProduct = Object.keys(currentTeam?.has_completed_onboarding_for || {}).length === 0
    const products = billing?.products || []

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
                            .filter(
                                (product) =>
                                    !product.contact_support &&
                                    !product.inclusion_only &&
                                    product.type !== 'data_warehouse'
                            )
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
