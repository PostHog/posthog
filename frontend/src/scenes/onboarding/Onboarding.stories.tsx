import { Meta } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import billingUnsubscribedJson from '~/mocks/fixtures/_billing_unsubscribed.json'
import { billingJson } from '~/mocks/fixtures/_billing_v2'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { BillingProductV2Type, ProductKey } from '~/types'

import { onboardingLogic, OnboardingStepKey } from './onboardingLogic'

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
            '/api/billing-v2/': {
                ...billingJson,
            },
        },
    })
    useMountedLogic(onboardingLogic)
    const { setProduct } = useActions(onboardingLogic)

    useEffect(() => {
        const product: BillingProductV2Type = billingJson.products[1] as unknown as BillingProductV2Type
        setProduct(product)
        router.actions.push(urls.onboarding(ProductKey.SESSION_REPLAY) + '?step=install')
    }, [])
    return <App />
}

export const _OnboardingBilling = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing-v2/': {
                ...billingUnsubscribedJson,
            },
        },
    })

    const { setProduct } = useActions(onboardingLogic)

    useEffect(() => {
        setProduct(billingUnsubscribedJson.products[1] as unknown as BillingProductV2Type)
        router.actions.push(urls.onboarding(ProductKey.SESSION_REPLAY, OnboardingStepKey.PLANS))
    }, [])
    return <App />
}
