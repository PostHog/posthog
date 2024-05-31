import { Meta } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import billingUnsubscribedJson from '~/mocks/fixtures/_billing_unsubscribed.json'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { OnboardingProduct, ProductKey } from '~/types'

import { availableOnboardingProducts, onboardingLogic, OnboardingStepKey } from './onboardingLogic'

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
            },
        }),
    ],
}
export default meta
export const _OnboardingSDKs = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing/': {
                ...billingJson,
            },
        },
    })
    useMountedLogic(onboardingLogic)
    const { setProduct } = useActions(onboardingLogic)

    useEffect(() => {
        const product: OnboardingProduct = availableOnboardingProducts[ProductKey.PRODUCT_ANALYTICS]
        setProduct(product)
        router.actions.push(urls.onboarding(ProductKey.SESSION_REPLAY) + '?step=install')
    }, [])
    return <App />
}

export const _OnboardingBilling = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing/': {
                ...billingUnsubscribedJson,
            },
        },
    })

    const { setProduct } = useActions(onboardingLogic)

    useEffect(() => {
        setProduct(availableOnboardingProducts[ProductKey.PRODUCT_ANALYTICS])
        router.actions.push(urls.onboarding(ProductKey.SESSION_REPLAY, OnboardingStepKey.PLANS))
    }, [])
    return <App />
}
