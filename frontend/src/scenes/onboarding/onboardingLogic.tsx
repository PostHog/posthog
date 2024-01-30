import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic, FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { BillingProductV2Type, ProductKey } from '~/types'

import type { onboardingLogicType } from './onboardingLogicType'

export interface OnboardingLogicProps {
    productKey: ProductKey | null
}

export enum OnboardingStepKey {
    PRODUCT_INTRO = 'product_intro',
    SDKS = 'sdks',
    BILLING = 'billing',
    OTHER_PRODUCTS = 'other_products',
    VERIFY = 'verify',
    PRODUCT_CONFIGURATION = 'configure',
    INVITE_TEAMMATES = 'invite_teammates',
}

// These types have to be set like this, so that kea typegen is happy
export type AllOnboardingSteps = OnboardingStep[]
export type OnboardingStep = JSX.Element

export const getProductUri = (productKey: ProductKey, featureFlags?: FeatureFlagsSet): string => {
    switch (productKey) {
        case ProductKey.PRODUCT_ANALYTICS:
            return featureFlags && featureFlags[FEATURE_FLAGS.REDIRECT_WEB_PRODUCT_ANALYTICS_ONBOARDING] === 'test'
                ? combineUrl(urls.webAnalytics(), { onboarding_completed: true }).url
                : combineUrl(urls.insights(), { onboarding_completed: true }).url
        case ProductKey.SESSION_REPLAY:
            return urls.replay()
        case ProductKey.FEATURE_FLAGS:
            return urls.featureFlags()
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
        values: [billingLogic, ['billing'], teamLogic, ['currentTeam'], featureFlagLogic, ['featureFlags']],
        actions: [billingLogic, ['loadBillingSuccess'], teamLogic, ['updateCurrentTeamSuccess']],
    }),
    actions({
        setProduct: (product: BillingProductV2Type | null) => ({ product }),
        setProductKey: (productKey: string | null) => ({ productKey }),
        completeOnboarding: (nextProductKey?: string) => ({ nextProductKey }),
        setAllOnboardingSteps: (allOnboardingSteps: AllOnboardingSteps) => ({ allOnboardingSteps }),
        setStepKey: (stepKey: OnboardingStepKey) => ({ stepKey }),
        setSubscribedDuringOnboarding: (subscribedDuringOnboarding: boolean) => ({ subscribedDuringOnboarding }),
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
    })),
    selectors({
        onCompleteOnboardingRedirectUrl: [
            (s) => [s.featureFlags, s.productKey],
            (featureFlags: FeatureFlagsSet, productKey: string | null) => {
                return productKey ? getProductUri(productKey as ProductKey, featureFlags) : urls.default()
            },
        ],
        totalOnboardingSteps: [
            (s) => [s.allOnboardingSteps],
            (allOnboardingSteps: AllOnboardingSteps) => allOnboardingSteps.length,
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
            (s) => [s.product, s.subscribedDuringOnboarding],
            (product: BillingProductV2Type | null, subscribedDuringOnboarding: boolean) => {
                const hasAllAddons = product?.addons?.every((addon) => addon.subscribed)
                return !product?.subscribed || !hasAllAddons || subscribedDuringOnboarding
            },
        ],
        shouldShowOtherProductsStep: [
            (s) => [s.suggestedProducts, s.isFirstProductOnboarding],
            (suggestedProducts: BillingProductV2Type[], isFirstProductOnboarding: boolean) =>
                suggestedProducts.length > 0 && isFirstProductOnboarding,
        ],
        suggestedProducts: [
            (s) => [s.billing, s.product, s.currentTeam],
            (billing, product, currentTeam) =>
                billing?.products?.filter(
                    (p) =>
                        p.type !== product?.type &&
                        !p.contact_support &&
                        !p.inclusion_only &&
                        !currentTeam?.has_completed_onboarding_for?.[p.type]
                ) || [],
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
                return [`/onboarding/${values.productKey}`, { step: stepKey }]
            } else {
                return [`/onboarding/${values.productKey}`]
            }
        },
        goToNextStep: () => {
            const currentStepIndex = values.allOnboardingSteps.findIndex(
                (step) => step.props.stepKey === values.stepKey
            )
            const nextStep = values.allOnboardingSteps[currentStepIndex + 1]
            if (nextStep) {
                return [`/onboarding/${values.productKey}`, { step: nextStep.props.stepKey }]
            } else {
                return [`/onboarding/${values.productKey}`]
            }
        },
        goToPreviousStep: () => {
            const currentStepIndex = values.allOnboardingSteps.findIndex(
                (step) => step.props.stepKey === values.stepKey
            )
            const previousStep = values.allOnboardingSteps[currentStepIndex - 1]
            if (previousStep) {
                return [`/onboarding/${values.productKey}`, { step: previousStep.props.stepKey }]
            } else {
                return [`/onboarding/${values.productKey}`]
            }
        },
        updateCurrentTeamSuccess(val) {
            if (values.productKey && val.payload?.has_completed_onboarding_for?.[values.productKey]) {
                return [values.onCompleteOnboardingRedirectUrl]
            }
        },
    })),
    urlToAction(({ actions, values }) => ({
        '/onboarding/:productKey(/:intro)': ({ productKey, intro }, { success, upgraded, step }) => {
            if (!productKey) {
                window.location.href = urls.default()
                return
            }
            if (intro === 'intro') {
                // this prevents us from jumping straight back into onboarding if they are trying to see the intro again
                actions.setAllOnboardingSteps([])
            }
            if (success || upgraded) {
                actions.setSubscribedDuringOnboarding(true)
            }
            if (productKey !== values.productKey) {
                actions.setProductKey(productKey)
            }
            if (step) {
                actions.setStepKey(step)
            } else {
                actions.resetStepKey()
            }
        },
    })),
])
