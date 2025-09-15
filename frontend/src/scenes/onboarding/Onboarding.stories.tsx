import { Meta } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { router } from 'kea-router'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import billingUnsubscribedJson from '~/mocks/fixtures/_billing_unsubscribed.json'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { OnboardingProduct, OnboardingStepKey, ProductKey } from '~/types'

import { onboardingLogic } from './onboardingLogic'
import { availableOnboardingProducts } from './utils'

const meta: Meta = {
    title: 'Scenes-Other/Onboarding',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    cloud: true,
                    realm: 'cloud',
                },
                '/stats': {},
                '/events': {},
                '/api/billing/': {
                    ...billingJson,
                },
                '/api/environments/:team_id/external_data_sources/wizard': () => {
                    return [
                        200,
                        {
                            Stripe: {
                                name: 'Stripe',
                                iconPath: '/static/services/stripe.png',
                                fields: [],
                                caption: '',
                            },
                        },
                    ]
                },
            },
            patch: {
                '/api/environments/@current/add_product_intent/': {},
            },
        }),
    ],
}
export default meta

export const _OnboardingSDKs = (): JSX.Element => {
    useMountedLogic(onboardingLogic)
    const { setProduct } = useActions(onboardingLogic)

    useDelayedOnMountEffect(() => {
        const product: OnboardingProduct = availableOnboardingProducts[ProductKey.PRODUCT_ANALYTICS]
        setProduct(product)
        router.actions.push(urls.onboarding(ProductKey.PRODUCT_ANALYTICS, OnboardingStepKey.INSTALL))
    })

    return <App />
}

export const _OnboardingProductConfiguration = (): JSX.Element => {
    useMountedLogic(onboardingLogic)

    const { setProduct } = useActions(onboardingLogic)

    useDelayedOnMountEffect(() => {
        setProduct(availableOnboardingProducts[ProductKey.SESSION_REPLAY])
        router.actions.push(urls.onboarding(ProductKey.SESSION_REPLAY, OnboardingStepKey.PRODUCT_CONFIGURATION))
    })

    return <App />
}

export const _OnboardingBilling = (): JSX.Element => {
    useMountedLogic(onboardingLogic)

    useStorybookMocks({
        get: {
            '/api/billing/': {
                ...billingUnsubscribedJson,
            },
        },
    })

    const { setProduct } = useActions(onboardingLogic)

    useDelayedOnMountEffect(() => {
        setProduct(availableOnboardingProducts[ProductKey.PRODUCT_ANALYTICS])
        router.actions.push(urls.onboarding(ProductKey.PRODUCT_ANALYTICS, OnboardingStepKey.PLANS))
    })

    return <App />
}

export const _OnboardingInvite = (): JSX.Element => {
    useMountedLogic(onboardingLogic)

    const { setProduct } = useActions(onboardingLogic)

    useDelayedOnMountEffect(() => {
        setProduct(availableOnboardingProducts[ProductKey.PRODUCT_ANALYTICS])
        router.actions.push(urls.onboarding(ProductKey.PRODUCT_ANALYTICS, OnboardingStepKey.INVITE_TEAMMATES))
    })

    return <App />
}

export const _OnboardingReverseProxy = (): JSX.Element => {
    useMountedLogic(onboardingLogic)

    const { setProduct } = useActions(onboardingLogic)

    useDelayedOnMountEffect(() => {
        setProduct(availableOnboardingProducts[ProductKey.FEATURE_FLAGS])
        router.actions.push(urls.onboarding(ProductKey.FEATURE_FLAGS, OnboardingStepKey.REVERSE_PROXY))
    })

    return <App />
}

export const _OnboardingLinkData = (): JSX.Element => {
    useMountedLogic(onboardingLogic)

    const { setProduct } = useActions(onboardingLogic)

    useDelayedOnMountEffect(() => {
        setProduct(availableOnboardingProducts[ProductKey.DATA_WAREHOUSE])
        router.actions.push(urls.onboarding(ProductKey.DATA_WAREHOUSE, OnboardingStepKey.LINK_DATA))
    })

    return <App />
}
