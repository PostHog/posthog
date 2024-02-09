import { IconCheck, IconMap, IconMessage, IconStack } from '@posthog/icons'
import { LemonButton, Link, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { WavingHog } from 'lib/components/hedgehogs'
import React from 'react'
import { convertLargeNumberToWords } from 'scenes/billing/billing-utils'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'
import { ProductPricingModal } from 'scenes/billing/ProductPricingModal'
import { getProductIcon } from 'scenes/products/Products'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { BillingProductV2Type, BillingV2FeatureType, ProductKey } from '~/types'

import { onboardingLogic } from './onboardingLogic'

export const scene: SceneExport = {
    component: OnboardingProductIntroduction,
    logic: onboardingLogic,
    paramsToProps: ({ params: { productKey } }) => ({ productKey }),
}

export const Feature = ({ name, description, images }: BillingV2FeatureType): JSX.Element => {
    return images ? (
        <li className="text-center">
            <div className="mb-2 w-full rounded">
                <img src={images.light} className="w-full rounded" />
            </div>
            <h4 className="mb-1 leading-tight text-lg">{name}</h4>
            <p className="text-[15px]">{description}</p>
        </li>
    ) : (
        <></>
    )
}

export const Subfeature = ({ name, description, icon_key }: BillingV2FeatureType): JSX.Element => {
    return (
        <li className="rounded-lg p-4 sm:p-6 sm:pb-8 bg-primary-alt-highlight">
            <span className="inline-block text-2xl mb-2 opacity-75">{getProductIcon(icon_key)}</span>
            <h3 className="text-[17px] mb-1 leading-tight">{name}</h3>
            <p className="m-0 text-[15px]">{description}</p>
        </li>
    )
}

const GetStartedButton = ({ product }: { product: BillingProductV2Type }): JSX.Element => {
    const cta: Partial<Record<ProductKey, string>> = {
        [ProductKey.SESSION_REPLAY]: 'Start recording my website',
        [ProductKey.FEATURE_FLAGS]: 'Create a feature flag or experiment',
        [ProductKey.SURVEYS]: 'Create a survey',
    }

    return (
        <div className="flex gap-x-4 items-center">
            <LemonButton
                to={urls.onboarding(product.type, undefined, true)}
                type="primary"
                status="alt"
                data-attr={`${product.type}-onboarding`}
                center
                className="max-w-max"
            >
                {cta[product.type] || 'Get started'}
            </LemonButton>
        </div>
    )
}

const PricingSection = ({ product }: { product: BillingProductV2Type }): JSX.Element => {
    const { currentAndUpgradePlans, isPricingModalOpen } = useValues(billingProductLogic({ product: product }))
    const { toggleIsPricingModalOpen } = useActions(billingProductLogic({ product: product }))
    const planForStats = currentAndUpgradePlans.upgradePlan || currentAndUpgradePlans.currentPlan
    const pricingListItems = [
        planForStats.tiers?.[0].up_to && (
            <>
                Get{' '}
                <b>
                    {convertLargeNumberToWords(planForStats.tiers?.[0].up_to, null)} {product.unit}s free
                </b>{' '}
                every month.
            </>
        ),
        planForStats.tiers?.[0].up_to && (
            <>
                Then just <span className="font-bold">${planForStats.tiers?.[1].unit_amount_usd}</span>/{product.unit}{' '}
                after that, with{' '}
                <Link onClick={() => toggleIsPricingModalOpen()} className="font-bold">
                    volume discounts
                </Link>{' '}
                automatically applied.
            </>
        ),
        <>
            Set <b>usage limits as low as $0</b> so you never get an unexpected bill.
        </>,
        <>Pay only for what you use.</>,
        <>
            Or, stay on our generous free plan if you'd like - you still get{' '}
            <b>
                {convertLargeNumberToWords(
                    currentAndUpgradePlans.currentPlan.free_allocation ||
                        currentAndUpgradePlans.downgradePlan.free_allocation ||
                        0,
                    null
                )}{' '}
                {product.unit}s free
            </b>{' '}
            every month.
        </>,
    ]

    return (
        <div className="w-full max-w-screen-xl">
            <h3 className="mb-4 text-2xl font-bold">Usage-based pricing that only scales when you do</h3>
            <ul className="pl-2 flex flex-col gap-y-1">
                {pricingListItems.map((item, i) => (
                    <li className="flex gap-x-2 items-start" key={`pricing-item-${i}`}>
                        <IconCheck className="inline-block text-success shrink-0 mt-1" />
                        <span>{item}</span>
                    </li>
                ))}
            </ul>
            <ProductPricingModal
                product={product}
                modalOpen={isPricingModalOpen}
                planKey={planForStats.plan_key}
                onClose={toggleIsPricingModalOpen}
            />
        </div>
    )
}

export function OnboardingProductIntroduction(): JSX.Element | null {
    const { product } = useValues(onboardingLogic)
    const websiteSlug: Partial<Record<ProductKey, string>> = {
        [ProductKey.SESSION_REPLAY]: 'session-replay',
        [ProductKey.FEATURE_FLAGS]: 'feature-flags',
        [ProductKey.SURVEYS]: 'surveys',
        [ProductKey.EXPERIMENTS]: 'experimentation',
        [ProductKey.PRODUCT_ANALYTICS]: 'product-analytics',
    }

    return product ? (
        <>
            <div className="unsubscribed-product-landing-page -m-4">
                <header className="bg-primary-alt-highlight border-b border-t border-border flex justify-center p-8">
                    <div className="grid md:grid-cols-2 items-center gap-8 w-full max-w-screen-xl">
                        <div className="">
                            <h3 className="text-4xl font-bold">{product.headline}</h3>
                            <p>{product.description}</p>
                            <GetStartedButton product={product} />
                        </div>
                        {product.image_url && (
                            <aside className="text-right my-2 hidden md:block">
                                <img src={product.image_url || undefined} className="max-w-96" />
                            </aside>
                        )}
                    </div>
                </header>
                {product.screenshot_url && (
                    <div className="flex justify-center">
                        <div className="max-w-6xl mt-8 -mb-12">
                            <img src={product.screenshot_url || undefined} className="w-full" />
                        </div>
                    </div>
                )}

                <div className="p-8 py-8 border-t border-border flex justify-center">
                    <div className="max-w-screen-xl">
                        <h3 className="mb-6 text-2xl font-bold">Features</h3>
                        <ul className="list-none p-0 grid grid-cols-2 md:grid-cols-3 gap-8 mb-8 ">
                            {product.features
                                .filter((feature) => feature.type == 'primary')
                                .map((feature, i) => {
                                    return (
                                        <React.Fragment key={`${product.type}-feature-${i}`}>
                                            <Feature {...feature} />
                                        </React.Fragment>
                                    )
                                })}
                        </ul>

                        <ul className="list-none p-0 grid grid-cols-2 md:grid-cols-3 gap-4">
                            {product.features
                                .filter((feature) => feature.type == 'secondary')
                                .map((subfeature, i) => {
                                    return (
                                        <React.Fragment key={`${product.type}-subfeature-${i}`}>
                                            <Subfeature {...subfeature} />
                                        </React.Fragment>
                                    )
                                })}
                        </ul>
                        <div className="mt-12">
                            <h3 className="mb-4 text-lg font-bold">Get the most out of {product.name}</h3>
                            <ul className="flex flex-col sm:flex-row gap-x-8 gap-y-2">
                                <li>
                                    <Link to={product.docs_url} target="_blank">
                                        <IconStack className="mr-2 text-xl" />
                                        <span className="font-bold">Product docs</span>
                                    </Link>
                                </li>
                                <li>
                                    <Link
                                        to={`https://posthog.com/tutorials/${websiteSlug[product.type]}`}
                                        target="_blank"
                                    >
                                        <IconMap className="mr-2 text-xl" />
                                        <span className="font-bold">Tutorials</span>
                                    </Link>
                                </li>
                                <li>
                                    <Link
                                        to={`https://posthog.com/questions/topic/${websiteSlug[product.type]}`}
                                        target="_blank"
                                    >
                                        <IconMessage className="mr-2 text-xl" />
                                        <span className="font-bold">Community</span>
                                    </Link>
                                </li>
                            </ul>
                        </div>
                    </div>
                </div>
                <div className="p-8 py-12 border-t border-border">
                    <div className="max-w-screen-xl m-auto">
                        <PricingSection product={product} />
                    </div>
                </div>
                <div className="mb-12 flex justify-center px-8">
                    <div className="w-full max-w-screen-xl rounded bg-primary-alt-highlight border border-border p-6 flex justify-between items-center gap-x-12">
                        <div>
                            <h3 className="mb-4 text-2xl font-bold">Get started with {product.name}</h3>
                            <p className="text-sm max-w-2xl">{product.description}</p>
                            <GetStartedButton product={product} />
                        </div>
                        <div className="w-24 hidden sm:block">
                            <WavingHog className="h-full w-full" />
                        </div>
                    </div>
                </div>
            </div>
        </>
    ) : (
        <div className="w-full text-center text-3xl mt-12">
            <Spinner />
        </div>
    )
}
