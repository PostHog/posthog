import { Meta } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { router } from 'kea-router'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { onboardingLogic } from '../onboardingLogic'
import { availableOnboardingProducts } from '../utils'

const meta: Meta = {
    title: 'Scenes-Other/Onboarding/SDKs',
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
                '/api/billing/': {
                    ...billingJson,
                },
            },
        }),
    ],
}
export default meta

// LLM Analytics SDKs - includes OpenAI, Anthropic, Vercel AI SDK, LangChain icons
export const LLMAnalyticsSDKs = (): JSX.Element => {
    useMountedLogic(onboardingLogic)
    const { setProduct } = useActions(onboardingLogic)

    useDelayedOnMountEffect(() => {
        setProduct(availableOnboardingProducts[ProductKey.LLM_ANALYTICS])
        router.actions.push(urls.onboarding(ProductKey.LLM_ANALYTICS, OnboardingStepKey.INSTALL))
    })

    return <App />
}

LLMAnalyticsSDKs.parameters = {
    testOptions: {
        waitForSelector: '[data-attr="sdk-continue"]',
    },
}

// Product Analytics SDKs - shows all web/mobile/server SDKs
export const ProductAnalyticsSDKs = (): JSX.Element => {
    useMountedLogic(onboardingLogic)
    const { setProduct } = useActions(onboardingLogic)

    useDelayedOnMountEffect(() => {
        setProduct(availableOnboardingProducts[ProductKey.PRODUCT_ANALYTICS])
        router.actions.push(urls.onboarding(ProductKey.PRODUCT_ANALYTICS, OnboardingStepKey.INSTALL))
    })

    return <App />
}

ProductAnalyticsSDKs.parameters = {
    testOptions: {
        waitForSelector: '[data-attr="sdk-continue"]',
    },
}
