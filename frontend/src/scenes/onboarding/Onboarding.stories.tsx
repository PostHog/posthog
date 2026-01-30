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
import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

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
                            // 4 featured ones
                            Github: {
                                name: 'Github',
                                iconPath: '/static/services/github.png',
                                fields: [],
                                caption: '',
                                featured: true,
                            },
                            Hubspot: {
                                name: 'Hubspot',
                                iconPath: '/static/services/hubspot.png',
                                fields: [],
                                caption: '',
                                featured: true,
                            },
                            Postgres: {
                                name: 'Postgres',
                                iconPath: '/static/services/postgres.png',
                                fields: [],
                                caption: '',
                                featured: true,
                            },
                            Stripe: {
                                name: 'Stripe',
                                iconPath: '/static/services/stripe.png',
                                fields: [],
                                caption: '',
                                featured: true,
                            },
                            // Extra sources to be displayed under button
                            Ashby: {
                                name: 'Ashby',
                                iconPath: '/static/services/ashby.png',
                                fields: [],
                                caption: '',
                                featured: false,
                            },
                            Supabase: {
                                name: 'Supabase',
                                iconPath: '/static/services/supabase.png',
                                fields: [],
                                caption: '',
                                featured: false,
                            },
                            Shopify: {
                                name: 'Shopify',
                                iconPath: '/static/services/shopify.png',
                                fields: [],
                                caption: '',
                                featured: false,
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

// ==========================================
// SDK Install (one example)
// ==========================================

export const SDKInstall = (): JSX.Element => {
    useMountedLogic(onboardingLogic)
    const { setProduct } = useActions(onboardingLogic)

    useDelayedOnMountEffect(() => {
        setProduct(availableOnboardingProducts[ProductKey.PRODUCT_ANALYTICS])
        router.actions.push(
            urls.onboarding({ productKey: ProductKey.PRODUCT_ANALYTICS, stepKey: OnboardingStepKey.INSTALL })
        )
    })

    return <App />
}
SDKInstall.parameters = {
    testOptions: { waitForSelector: '[data-attr="sdk-continue"]' },
}

export const LLMAnalyticsSDKInstall = (): JSX.Element => {
    useMountedLogic(onboardingLogic)
    const { setProduct } = useActions(onboardingLogic)

    useDelayedOnMountEffect(() => {
        setProduct(availableOnboardingProducts[ProductKey.LLM_ANALYTICS])
        router.actions.push(
            urls.onboarding({ productKey: ProductKey.LLM_ANALYTICS, stepKey: OnboardingStepKey.INSTALL })
        )
    })

    return <App />
}
LLMAnalyticsSDKInstall.parameters = {
    testOptions: { waitForSelector: '[data-attr="sdk-continue"]' },
}

// ==========================================
// Product Configuration Steps
// ==========================================

export const ProductAnalyticsConfiguration = (): JSX.Element => {
    useMountedLogic(onboardingLogic)
    const { setProduct } = useActions(onboardingLogic)

    useDelayedOnMountEffect(() => {
        setProduct(availableOnboardingProducts[ProductKey.PRODUCT_ANALYTICS])
        router.actions.push(
            urls.onboarding({
                productKey: ProductKey.PRODUCT_ANALYTICS,
                stepKey: OnboardingStepKey.PRODUCT_CONFIGURATION,
            })
        )
    })

    return <App />
}

export const SessionReplayConfiguration = (): JSX.Element => {
    useMountedLogic(onboardingLogic)
    const { setProduct } = useActions(onboardingLogic)

    useDelayedOnMountEffect(() => {
        setProduct(availableOnboardingProducts[ProductKey.SESSION_REPLAY])
        router.actions.push(
            urls.onboarding({ productKey: ProductKey.SESSION_REPLAY, stepKey: OnboardingStepKey.PRODUCT_CONFIGURATION })
        )
    })

    return <App />
}

export const SessionReplayOptIn = (): JSX.Element => {
    useMountedLogic(onboardingLogic)
    const { setProduct } = useActions(onboardingLogic)

    useDelayedOnMountEffect(() => {
        setProduct(availableOnboardingProducts[ProductKey.PRODUCT_ANALYTICS])
        router.actions.push(
            urls.onboarding({ productKey: ProductKey.PRODUCT_ANALYTICS, stepKey: OnboardingStepKey.SESSION_REPLAY })
        )
    })

    return <App />
}

// ==========================================
// Web Analytics
// ==========================================

export const AuthorizedDomains = (): JSX.Element => {
    useMountedLogic(onboardingLogic)
    const { setProduct } = useActions(onboardingLogic)

    useDelayedOnMountEffect(() => {
        setProduct(availableOnboardingProducts[ProductKey.WEB_ANALYTICS])
        router.actions.push(
            urls.onboarding({ productKey: ProductKey.WEB_ANALYTICS, stepKey: OnboardingStepKey.AUTHORIZED_DOMAINS })
        )
    })

    return <App />
}

// ==========================================
// Data Warehouse
// ==========================================

export const LinkData = (): JSX.Element => {
    useMountedLogic(onboardingLogic)
    const { setProduct } = useActions(onboardingLogic)

    useDelayedOnMountEffect(() => {
        setProduct(availableOnboardingProducts[ProductKey.DATA_WAREHOUSE])
        router.actions.push(
            urls.onboarding({ productKey: ProductKey.DATA_WAREHOUSE, stepKey: OnboardingStepKey.LINK_DATA })
        )
    })

    return <App />
}

// ==========================================
// Error Tracking
// ==========================================

export const SourceMaps = (): JSX.Element => {
    useMountedLogic(onboardingLogic)
    const { setProduct } = useActions(onboardingLogic)

    useDelayedOnMountEffect(() => {
        setProduct(availableOnboardingProducts[ProductKey.ERROR_TRACKING])
        router.actions.push(
            urls.onboarding({ productKey: ProductKey.ERROR_TRACKING, stepKey: OnboardingStepKey.SOURCE_MAPS })
        )
    })

    return <App />
}

export const Alerts = (): JSX.Element => {
    useMountedLogic(onboardingLogic)
    const { setProduct } = useActions(onboardingLogic)

    useDelayedOnMountEffect(() => {
        setProduct(availableOnboardingProducts[ProductKey.ERROR_TRACKING])
        router.actions.push(
            urls.onboarding({ productKey: ProductKey.ERROR_TRACKING, stepKey: OnboardingStepKey.ALERTS })
        )
    })

    return <App />
}

// ==========================================
// Shared Steps
// ==========================================

export const BillingPlans = (): JSX.Element => {
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
        router.actions.push(
            urls.onboarding({ productKey: ProductKey.PRODUCT_ANALYTICS, stepKey: OnboardingStepKey.PLANS })
        )
    })

    return <App />
}

export const InviteTeammates = (): JSX.Element => {
    useMountedLogic(onboardingLogic)
    const { setProduct } = useActions(onboardingLogic)

    useDelayedOnMountEffect(() => {
        setProduct(availableOnboardingProducts[ProductKey.PRODUCT_ANALYTICS])
        router.actions.push(
            urls.onboarding({ productKey: ProductKey.PRODUCT_ANALYTICS, stepKey: OnboardingStepKey.INVITE_TEAMMATES })
        )
    })

    return <App />
}

export const ReverseProxy = (): JSX.Element => {
    useMountedLogic(onboardingLogic)
    const { setProduct } = useActions(onboardingLogic)

    useDelayedOnMountEffect(() => {
        setProduct(availableOnboardingProducts[ProductKey.FEATURE_FLAGS])
        router.actions.push(
            urls.onboarding({ productKey: ProductKey.FEATURE_FLAGS, stepKey: OnboardingStepKey.REVERSE_PROXY })
        )
    })

    return <App />
}
