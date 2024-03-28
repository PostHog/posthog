import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic, FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { BillingProductV2Type, Breadcrumb, ProductKey } from '~/types'

import type { onboardingLogicType } from './onboardingLogicType'

export interface OnboardingLogicProps {
    productKey: ProductKey | null
}

export enum OnboardingStepKey {
    PRODUCT_INTRO = 'product_intro',
    INSTALL = 'install',
    PLANS = 'plans',
    VERIFY = 'verify',
    PRODUCT_CONFIGURATION = 'configure',
    REVERSE_PROXY = 'proxy',
    INVITE_TEAMMATES = 'invite_teammates',
}

const productKeyToProductName = {
    [ProductKey.PRODUCT_ANALYTICS]: 'Product Analytics',
    [ProductKey.SESSION_REPLAY]: 'Session Replay',
    [ProductKey.FEATURE_FLAGS]: 'Feature Flags',
    [ProductKey.SURVEYS]: 'Surveys',
}

const productKeyToURL = {
    [ProductKey.PRODUCT_ANALYTICS]: urls.insights(),
    [ProductKey.SESSION_REPLAY]: urls.replay(),
    [ProductKey.FEATURE_FLAGS]: urls.featureFlags(),
    [ProductKey.SURVEYS]: urls.surveys(),
}

const productKeyToScene = {
    [ProductKey.PRODUCT_ANALYTICS]: Scene.SavedInsights,
    [ProductKey.SESSION_REPLAY]: Scene.Replay,
    [ProductKey.FEATURE_FLAGS]: Scene.FeatureFlags,
    [ProductKey.SURVEYS]: Scene.Surveys,
}

export const stepKeyToTitle = (stepKey?: OnboardingStepKey): undefined | string => {
    return (
        stepKey &&
        stepKey
            .split('_')
            .map((part, i) => (i == 0 ? part[0].toUpperCase() + part.substring(1) : part))
            .join(' ')
    )
}

// These types have to be set like this, so that kea typegen is happy
export type AllOnboardingSteps = OnboardingStep[]
export type OnboardingStep = JSX.Element

export const getProductUri = (productKey: ProductKey): string => {
    switch (productKey) {
        case ProductKey.PRODUCT_ANALYTICS:
            return urls.insightNew()
        case ProductKey.SESSION_REPLAY:
            return urls.replay()
        case ProductKey.FEATURE_FLAGS:
            return urls.featureFlag('new')
        case ProductKey.SURVEYS:
            return urls.surveyTemplates()
        default:
            return urls.default()
    }
}

export const onboardingLogic = kea<onboardingLogicType>([
    props({} as OnboardingLogicProps),
    path(['scenes', 'onboarding', 'onboardingLogic']),
    connect({
        values: [
            billingLogic,
            ['billing'],
            teamLogic,
            ['currentTeam'],
            featureFlagLogic,
            ['featureFlags'],
            userLogic,
            ['user'],
            preflightLogic,
            ['isCloudOrDev'],
        ],
        actions: [billingLogic, ['loadBillingSuccess'], teamLogic, ['updateCurrentTeam', 'updateCurrentTeamSuccess']],
    }),
    actions({
        setProduct: (product: BillingProductV2Type | null) => ({ product }),
        setProductKey: (productKey: string | null) => ({ productKey }),
        completeOnboarding: (nextProductKey?: string) => ({ nextProductKey }),
        setAllOnboardingSteps: (allOnboardingSteps: AllOnboardingSteps) => ({ allOnboardingSteps }),
        setStepKey: (stepKey: OnboardingStepKey) => ({ stepKey }),
        setSubscribedDuringOnboarding: (subscribedDuringOnboarding: boolean) => ({ subscribedDuringOnboarding }),
        setIncludeIntro: (includeIntro: boolean) => ({ includeIntro }),
        setTeamPropertiesForProduct: (productKey: ProductKey) => ({ productKey }),
        goToNextStep: true,
        goToPreviousStep: true,
        resetStepKey: true,
    }),
    reducers(() => ({
        productKey: [
            null as string | null,
            {
                setProductKey: (_, { productKey }) => productKey,
            },
        ],
        product: [
            null as BillingProductV2Type | null,
            {
                setProduct: (_, { product }) => product,
            },
        ],
        allOnboardingSteps: [
            [] as AllOnboardingSteps,
            {
                setAllOnboardingSteps: (_, { allOnboardingSteps }) => allOnboardingSteps,
            },
        ],
        stepKey: [
            '' as OnboardingStepKey,
            {
                setStepKey: (_, { stepKey }) => stepKey,
            },
        ],
        subscribedDuringOnboarding: [
            false,
            {
                setSubscribedDuringOnboarding: (_, { subscribedDuringOnboarding }) => subscribedDuringOnboarding,
            },
        ],
        includeIntro: [
            true,
            {
                setIncludeIntro: (_, { includeIntro }) => includeIntro,
            },
        ],
    })),
    selectors({
        breadcrumbs: [
            (s) => [s.productKey, s.stepKey],
            (productKey, stepKey): Breadcrumb[] => {
                return [
                    {
                        key: Scene.Onboarding,
                        name: productKeyToProductName[productKey ?? ''],
                        path: productKeyToURL[productKey ?? ''],
                    },
                    {
                        key: productKeyToScene[productKey ?? ''],
                        name: stepKeyToTitle(stepKey),
                        path: urls.onboarding(productKey ?? '', stepKey),
                    },
                ]
            },
        ],
        onCompleteOnboardingRedirectUrl: [
            (s) => [s.productKey],
            (productKey: string | null) => {
                return productKey ? getProductUri(productKey as ProductKey) : urls.default()
            },
        ],
        totalOnboardingSteps: [
            (s) => [s.allOnboardingSteps],
            (allOnboardingSteps: AllOnboardingSteps) => allOnboardingSteps.length,
        ],
        onboardingStepKeys: [
            (s) => [s.allOnboardingSteps],
            (allOnboardingSteps: AllOnboardingSteps) => {
                return allOnboardingSteps.map((step) => step.props.stepKey)
            },
        ],
        currentOnboardingStep: [
            (s) => [s.allOnboardingSteps, s.stepKey],
            (allOnboardingSteps: AllOnboardingSteps, stepKey: OnboardingStepKey): OnboardingStep | null =>
                allOnboardingSteps.find((step) => step.props.stepKey === stepKey) || null,
        ],
        hasNextStep: [
            (s) => [s.allOnboardingSteps, s.stepKey],
            (allOnboardingSteps: AllOnboardingSteps, stepKey: OnboardingStepKey) => {
                const currentStepIndex = allOnboardingSteps.findIndex((step) => step.props.stepKey === stepKey)
                return currentStepIndex < allOnboardingSteps.length - 1
            },
        ],
        hasPreviousStep: [
            (s) => [s.allOnboardingSteps, s.stepKey],
            (allOnboardingSteps: AllOnboardingSteps, stepKey: OnboardingStepKey) => {
                const currentStepIndex = allOnboardingSteps.findIndex((step) => step.props.stepKey === stepKey)
                return currentStepIndex > 0
            },
        ],
        shouldShowBillingStep: [
            (s) => [s.product, s.subscribedDuringOnboarding, s.isCloudOrDev],
            (product: BillingProductV2Type | null, subscribedDuringOnboarding: boolean, isCloudOrDev) => {
                if (!isCloudOrDev) {
                    return false
                }
                const hasAllAddons = product?.addons?.every((addon) => addon.subscribed)
                return !product?.subscribed || !hasAllAddons || subscribedDuringOnboarding
            },
        ],
        shouldShowReverseProxyStep: [
            (s) => [s.product, s.featureFlags],
            (product: BillingProductV2Type | null, featureFlags: FeatureFlagsSet) => {
                const productsWithReverseProxy = []
                if (featureFlags[FEATURE_FLAGS.REVERSE_PROXY_ONBOARDING] === 'test') {
                    productsWithReverseProxy.push(ProductKey.FEATURE_FLAGS)
                }
                return productsWithReverseProxy.includes(product?.type as ProductKey)
            },
        ],
        isStepKeyInvalid: [
            (s) => [s.stepKey, s.allOnboardingSteps, s.currentOnboardingStep],
            (stepKey: string, allOnboardingSteps: AllOnboardingSteps, currentOnboardingStep: React.ReactNode | null) =>
                (stepKey && allOnboardingSteps.length > 0 && !currentOnboardingStep) ||
                (!stepKey && allOnboardingSteps.length > 0),
        ],
        isFirstProductOnboarding: [
            (s) => [s.currentTeam],
            (currentTeam) => {
                return !Object.keys(currentTeam?.has_completed_onboarding_for || {}).some(
                    (key) => currentTeam?.has_completed_onboarding_for?.[key] === true
                )
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        loadBillingSuccess: () => {
            if (window.location.pathname.includes('/onboarding')) {
                actions.setProduct(values.billing?.products.find((p) => p.type === values.productKey) || null)
            }
        },
        setProduct: ({ product }) => {
            if (!product) {
                window.location.href = urls.default()
            } else {
                actions.resetStepKey()
            }
        },
        setTeamPropertiesForProduct: ({ productKey }) => {
            switch (productKey) {
                case ProductKey.PRODUCT_ANALYTICS:
                    return
                case ProductKey.SESSION_REPLAY:
                    actions.updateCurrentTeam({
                        session_recording_opt_in: true,
                        capture_console_log_opt_in: true,
                        capture_performance_opt_in: true,
                    })
                    return
                case ProductKey.FEATURE_FLAGS:
                    return
                default:
                    return
            }
        },
        setProductKey: ({ productKey }) => {
            if (!productKey) {
                window.location.href = urls.default()
                return
            }
            if (values.billing?.products?.length) {
                actions.setProduct(values.billing?.products.find((p) => p.type === values.productKey) || null)
            }
        },
        setSubscribedDuringOnboarding: ({ subscribedDuringOnboarding }) => {
            if (subscribedDuringOnboarding) {
                // we might not have the product key yet
                // if not we'll just use the current url to determine the product key
                const productKey = values.productKey || (window.location.pathname.split('/')[2] as ProductKey)
                eventUsageLogic.actions.reportSubscribedDuringOnboarding(productKey)
            }
        },

        completeOnboarding: ({ nextProductKey }) => {
            if (values.productKey) {
                const product = values.productKey
                eventUsageLogic.actions.reportOnboardingCompleted(product)
                if (nextProductKey) {
                    actions.setProductKey(nextProductKey)
                    router.actions.push(urls.onboarding(nextProductKey))
                }
                teamLogic.actions.updateCurrentTeam({
                    has_completed_onboarding_for: {
                        ...values.currentTeam?.has_completed_onboarding_for,
                        [product]: true,
                    },
                })
            }
        },
        setAllOnboardingSteps: () => {
            if (values.isStepKeyInvalid) {
                actions.resetStepKey()
            }
        },
        setStepKey: () => {
            if (values.isStepKeyInvalid) {
                actions.resetStepKey()
            }
        },
        resetStepKey: () => {
            values.allOnboardingSteps[0] && actions.setStepKey(values.allOnboardingSteps[0]?.props.stepKey)
        },
    })),
    actionToUrl(({ values }) => ({
        setStepKey: ({ stepKey }) => {
            if (stepKey) {
                return [`/onboarding/${values.productKey}`, { ...router.values.searchParams, step: stepKey }]
            } else {
                return [`/onboarding/${values.productKey}`, router.values.searchParams]
            }
        },
        goToNextStep: () => {
            const currentStepIndex = values.allOnboardingSteps.findIndex(
                (step) => step.props.stepKey === values.stepKey
            )
            const nextStep = values.allOnboardingSteps[currentStepIndex + 1]
            if (nextStep) {
                return [
                    `/onboarding/${values.productKey}`,
                    { ...router.values.searchParams, step: nextStep.props.stepKey },
                ]
            } else {
                return [`/onboarding/${values.productKey}`, router.values.searchParams]
            }
        },
        goToPreviousStep: () => {
            const currentStepIndex = values.allOnboardingSteps.findIndex(
                (step) => step.props.stepKey === values.stepKey
            )
            const previousStep = values.allOnboardingSteps[currentStepIndex - 1]
            if (previousStep) {
                return [
                    `/onboarding/${values.productKey}`,
                    { ...router.values.searchParams, step: previousStep.props.stepKey },
                ]
            } else {
                return [`/onboarding/${values.productKey}`, router.values.searchParams]
            }
        },
        updateCurrentTeamSuccess(val) {
            if (values.productKey && val.payload?.has_completed_onboarding_for?.[values.productKey]) {
                return [values.onCompleteOnboardingRedirectUrl]
            }
        },
    })),
    urlToAction(({ actions, values }) => ({
        '/onboarding/:productKey': ({ productKey }, { success, upgraded, step }) => {
            if (!productKey) {
                window.location.href = urls.default()
                return
            }

            if (success || upgraded) {
                actions.setSubscribedDuringOnboarding(true)
            }
            if (productKey !== values.productKey) {
                actions.setProductKey(productKey)
            }

            // Reset onboarding steps so they can be populated upon render in the component.
            actions.setAllOnboardingSteps([])

            if (step) {
                actions.setStepKey(step)
            } else {
                actions.resetStepKey()
            }
        },
    })),
])
