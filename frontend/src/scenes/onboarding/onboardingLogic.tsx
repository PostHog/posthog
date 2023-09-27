import { kea } from 'kea'
import { BillingProductV2Type, ProductKey } from '~/types'
import { urls } from 'scenes/urls'

import type { onboardingLogicType } from './onboardingLogicType'
import { billingLogic } from 'scenes/billing/billingLogic'
import { teamLogic } from 'scenes/teamLogic'

export interface OnboardingLogicProps {
    productKey: ProductKey | null
}

export enum OnboardingStepKey {
    PRODUCT_INTRO = 'product_intro',
    SDKS = 'sdks',
    BILLING = 'billing',
    OTHER_PRODUCTS = 'other_products',
    VERIFY = 'verify',
}

export type OnboardingStepMap = Record<OnboardingStepKey, string>

const onboardingStepMap: OnboardingStepMap = {
    [OnboardingStepKey.PRODUCT_INTRO]: 'OnboardingProductIntro',
    [OnboardingStepKey.SDKS]: 'SDKs',
    [OnboardingStepKey.BILLING]: 'OnboardingBillingStep',
    [OnboardingStepKey.OTHER_PRODUCTS]: 'OnboardingOtherProductsStep',
    [OnboardingStepKey.VERIFY]: 'OnboardingVerificationStep',
}

export type AllOnboardingSteps = JSX.Element[]

export const onboardingLogic = kea<onboardingLogicType>({
    props: {} as OnboardingLogicProps,
    path: ['scenes', 'onboarding', 'onboardingLogic'],
    connect: {
        values: [billingLogic, ['billing'], teamLogic, ['currentTeam']],
        actions: [billingLogic, ['loadBillingSuccess'], teamLogic, ['updateCurrentTeam']],
    },
    actions: {
        setProduct: (product: BillingProductV2Type | null) => ({ product }),
        setProductKey: (productKey: string | null) => ({ productKey }),
        setCurrentOnboardingStepNumber: (currentOnboardingStepNumber: number) => ({ currentOnboardingStepNumber }),
        completeOnboarding: (redirectUri?: string) => ({ redirectUri }),
        setAllOnboardingSteps: (allOnboardingSteps: AllOnboardingSteps) => ({ allOnboardingSteps }),
        setStepKey: (stepKey: string) => ({ stepKey }),
        setSubscribedDuringOnboarding: (subscribedDuringOnboarding: boolean) => ({ subscribedDuringOnboarding }),
    },
    reducers: () => ({
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
        currentOnboardingStepNumber: [
            1,
            {
                setCurrentOnboardingStepNumber: (_, { currentOnboardingStepNumber }) => currentOnboardingStepNumber,
            },
        ],
        allOnboardingSteps: [
            [] as AllOnboardingSteps,
            {
                setAllOnboardingSteps: (_, { allOnboardingSteps }) => allOnboardingSteps as AllOnboardingSteps,
            },
        ],
        stepKey: [
            '' as string,
            {
                setStepKey: (_, { stepKey }) => stepKey,
            },
        ],
        onCompleteOnbardingRedirectUrl: [
            urls.default() as string,
            {
                setProductKey: (_, { productKey }) => {
                    switch (productKey) {
                        case 'product_analytics':
                            return urls.default()
                        case 'session_replay':
                            return urls.replay()
                        case 'feature_flags':
                            return urls.featureFlags()
                        default:
                            return urls.default()
                    }
                },
            },
        ],
        subscribedDuringOnboarding: [
            false,
            {
                setSubscribedDuringOnboarding: (_, { subscribedDuringOnboarding }) => subscribedDuringOnboarding,
            },
        ],
    }),
    selectors: {
        totalOnboardingSteps: [
            (s) => [s.allOnboardingSteps],
            (allOnboardingSteps: AllOnboardingSteps) => allOnboardingSteps.length,
        ],
        shouldShowBillingStep: [
            (s) => [s.product, s.subscribedDuringOnboarding],
            (product: BillingProductV2Type | null, subscribedDuringOnboarding: boolean) => {
                const hasAllAddons = product?.addons?.every((addon) => addon.subscribed)
                return !product?.subscribed || !hasAllAddons || subscribedDuringOnboarding
            },
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
    },
    listeners: ({ actions, values }) => ({
        loadBillingSuccess: () => {
            actions.setProduct(values.billing?.products.find((p) => p.type === values.productKey) || null)
        },
        setProduct: ({ product }) => {
            if (!product) {
                window.location.href = urls.default()
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
        completeOnboarding: ({ redirectUri }) => {
            if (values.productKey) {
                // update the current team has_completed_onboarding_for field, only writing over the current product
                actions.updateCurrentTeam({
                    has_completed_onboarding_for: {
                        ...values.currentTeam?.has_completed_onboarding_for,
                        [values.productKey]: true,
                    },
                })
            }
            window.location.href = redirectUri || values.onCompleteOnbardingRedirectUrl
        },
        setAllOnboardingSteps: ({ allOnboardingSteps }) => {
            // once we have the onboarding steps we need to make sure the step key is valid,
            // and if so use it to set the step number. if not valid, remove it from the state.
            // valid step keys are either numbers (used for unnamed steps) or keys from the onboardingStepMap.
            // if it's a number, we try to convert it to a named step key using the onboardingStepMap.
            let stepKey = values.stepKey
            if (values.stepKey) {
                if (parseInt(values.stepKey) > 0) {
                    // try to convert the step number to a step key
                    const stepName = allOnboardingSteps[parseInt(values.stepKey) - 1]?.type?.name
                    const newStepKey = Object.keys(onboardingStepMap).find((key) => onboardingStepMap[key] === stepName)
                    if (stepName && stepKey) {
                        stepKey = newStepKey || stepKey
                        actions.setStepKey(stepKey)
                    }
                }
                if (stepKey in onboardingStepMap) {
                    const stepIndex = allOnboardingSteps
                        .map((step) => step.type.name)
                        .indexOf(onboardingStepMap[stepKey as OnboardingStepKey])
                    if (stepIndex > -1) {
                        actions.setCurrentOnboardingStepNumber(stepIndex + 1)
                    } else {
                        actions.setStepKey('')
                        actions.setCurrentOnboardingStepNumber(1)
                    }
                } else if (
                    // if it's a number, just use that and set the correct onboarding step number
                    parseInt(stepKey) > 1 &&
                    allOnboardingSteps.length > 0 &&
                    allOnboardingSteps[parseInt(stepKey) - 1]
                ) {
                    actions.setCurrentOnboardingStepNumber(parseInt(stepKey))
                }
            }
        },
        setStepKey: ({ stepKey }) => {
            // if the step key is invalid (doesn't exist in the onboardingStepMap or the allOnboardingSteps array)
            // remove it from the state. Numeric step keys are also allowed, as long as they are a valid
            // index for the allOnboardingSteps array.
            if (
                stepKey &&
                values.allOnboardingSteps.length > 0 &&
                (!values.allOnboardingSteps.find(
                    (step) => step.type.name === onboardingStepMap[stepKey as OnboardingStepKey]
                ) ||
                    !values.allOnboardingSteps[parseInt(stepKey) - 1])
            ) {
                actions.setStepKey('')
            }
        },
    }),
    actionToUrl: ({ values }) => ({
        setCurrentOnboardingStepNumber: () => {
            // when the current step number changes, update the url to reflect the new step
            const stepName = values.allOnboardingSteps[values.currentOnboardingStepNumber - 1]?.type?.name
            const stepKey =
                Object.keys(onboardingStepMap).find((key) => onboardingStepMap[key] === stepName) ||
                values.currentOnboardingStepNumber.toString()
            if (stepKey) {
                return [`/onboarding/${values.productKey}`, { step: stepKey }]
            } else {
                return [`/onboarding/${values.productKey}`]
            }
        },
    }),
    urlToAction: ({ actions, values }) => ({
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
            if (step && (step in onboardingStepMap || parseInt(step) > 0)) {
                actions.setStepKey(step)
            } else {
                actions.setCurrentOnboardingStepNumber(1)
            }
        },
    }),
})
