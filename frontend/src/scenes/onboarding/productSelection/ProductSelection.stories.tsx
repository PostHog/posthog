import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { productSelectionLogic } from 'scenes/onboarding/productSelection/productSelectionLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { ProductKey } from '~/queries/schema/schema-general'

const meta: Meta = {
    component: App,
    title: 'Scenes-Other/Onboarding/Product Selection',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
        pageUrl: urls.onboarding(),
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    cloud: true,
                    realm: 'cloud',
                },
                '/api/billing/': billingJson,
            },
            post: {
                '/api/environments/:team_id/onboarding/recommend_products/': {
                    products: ['product-analytics', 'session-replay', 'experiments'],
                    reasoning:
                        'Based on your goal to improve checkout conversion, we recommend Product Analytics for funnel analysis, Session Replay to watch user behavior, and Experiments to test improvements.',
                },
            },
            patch: {
                '/api/environments/@current/add_product_intent/': {},
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>
export const Base: Story = {}

export const WithAIFeatureFlag: Story = {
    parameters: { featureFlags: [FEATURE_FLAGS.ONBOARDING_AI_PRODUCT_RECOMMENDATIONS] },
}

export const AfterAIRecommendation: StoryFn = () => {
    useMountedLogic(productSelectionLogic)
    const { setAiRecommendation, setRecommendationSource, setSelectedProducts, setStep } =
        useActions(productSelectionLogic)

    useDelayedOnMountEffect(() => {
        router.actions.push(urls.onboarding())

        // Simulate AI recommendation result
        setAiRecommendation({
            products: ['product-analytics', 'session-replay', 'experiments'],
            reasoning:
                'Based on your goal to improve checkout conversion, we recommend Product Analytics for funnel analysis, Session Replay to watch user behavior, and Experiments to test improvements.',
        })
        setRecommendationSource('ai')
        setSelectedProducts([ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY, ProductKey.EXPERIMENTS])
        setStep('product_selection')
    })

    return <App />
}
AfterAIRecommendation.parameters = {
    testOptions: { waitForSelector: '[data-attr="product_analytics-onboarding-card"]' },
}
