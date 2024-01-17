import './onboarding.scss'

import { LemonButton, Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import React from 'react'
import { getProductIcon } from 'scenes/products/Products'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { BillingProductV2Type, BillingV2FeatureType } from '~/types'

import { onboardingLogic } from './onboardingLogic'

export const scene: SceneExport = {
    component: OnboardingProductIntroduction,
    logic: onboardingLogic,
}

export const Feature = ({ name, description, images }: BillingV2FeatureType): JSX.Element => {
    return images ? (
        <li className="text-center">
            <div className="mb-2 w-full border border-border rounded">
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
        <li className="rounded-lg p-4 sm:p-6 sm:pb-8">
            <span className="inline-block text-2xl mb-2 opacity-75">{getProductIcon(icon_key)}</span>
            <h3 className="text-[17px] mb-1 leading-tight">{name}</h3>
            <p className="m-0 text-[15px]">{description}</p>
        </li>
    )
}

const GetStartedButton = ({ product }: { product: BillingProductV2Type }): JSX.Element => {
    return (
        <div>
            <LemonButton
                to={urls.onboarding(product.type)}
                type="primary"
                status="alt"
                data-attr={`${product.type}-upgrade`}
                center
                className="max-w-max"
            >
                Get started with {product.name}
            </LemonButton>
        </div>
    )
}

export function OnboardingProductIntroduction(): JSX.Element | null {
    const { product } = useValues(onboardingLogic)
    return product ? (
        <>
            <div className="unsubscribed-product-landing-page">
                <header className="bg-primary-alt-highlight border-b border-t border-border">
                    <div className="grid grid-cols-2 items-center gap-8 max-w-screen-xl">
                        <div className="px-8">
                            <h2 className="text-2xl font-bold">{product.name}</h2>
                            <p className="text-base font-bold">{product.headline}</p>
                            <p>{product.description}</p>
                            <GetStartedButton product={product} />
                        </div>
                        <aside className="text-right">
                            <img src={product.image_url || undefined} className="max-w-full" />
                        </aside>
                    </div>
                </header>
                {product.screenshot_url && (
                    <div className="max-w-screen-xl flex justify-center">
                        <div className="max-w-6xl mt-12">
                            <img src={product.screenshot_url || undefined} className="w-full" />
                        </div>
                    </div>
                )}
                <div className="features p-8 py-12 border-t border-border">
                    <h3 className="mb-4 text-lg font-bold">Features</h3>
                    <ul className="list-none p-0 grid grid-cols-3 gap-8 mb-8 max-w-screen-xl">
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

                    <ul className="subfeatures list-none p-0 grid grid-cols-2 md:grid-cols-3 gap-4 max-w-screen-xl">
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
                </div>
                <div className="pb-12 px-8 max-w-screen-xl flex justify-center">
                    <GetStartedButton product={product} />
                </div>
            </div>
        </>
    ) : (
        <div className="w-full text-center text-3xl mt-12">
            <Spinner />
        </div>
    )
}
