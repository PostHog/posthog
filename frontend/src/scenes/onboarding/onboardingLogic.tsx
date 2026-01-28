import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { QUICK_START_PARAM } from 'lib/components/ProductSetup/globalSetupLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { ProductKey } from '~/queries/schema/schema-general'
import { Breadcrumb, OnboardingProduct, OnboardingStepKey } from '~/types'

import type { onboardingLogicType } from './onboardingLogicType'
import { availableOnboardingProducts } from './utils'

/** Interface for onboarding step components that have a static stepKey property */
export interface OnboardingStepComponentType<P = object> extends React.FC<P> {
    stepKey: OnboardingStepKey
}

/** A JSX element whose component type is an OnboardingStepComponentType */
export type OnboardingStepElement = React.ReactElement<unknown, OnboardingStepComponentType>

/** Helper to extract stepKey from a step element's component type */
const getStepKey = (step: OnboardingStepElement): OnboardingStepKey => {
    return step.type.stepKey
}

export interface OnboardingLogicProps {
    onCompleteOnboarding?: (key: ProductKey) => void
}

const STEP_KEY_TITLE_OVERRIDES: Partial<Record<OnboardingStepKey, string>> = {
    [OnboardingStepKey.LINK_DATA]: 'Import data',
}

export const stepKeyToTitle = (stepKey?: OnboardingStepKey): undefined | string => {
    if (!stepKey) {
        return undefined
    }
    if (STEP_KEY_TITLE_OVERRIDES[stepKey]) {
        return STEP_KEY_TITLE_OVERRIDES[stepKey]
    }
    return stepKey
        .split('_')
        .map((part, i) => (i == 0 ? part[0].toUpperCase() + part.substring(1) : part))
        .join(' ')
}

// These types have to be set like this, so that kea typegen is happy
export type OnboardingStepType = OnboardingStepElement

export const getOnboardingCompleteRedirectUri = (productKey: ProductKey): string => {
    let baseUrl: string
    switch (productKey) {
        case ProductKey.PRODUCT_ANALYTICS:
            baseUrl = urls.insightOptions()
            break
        case ProductKey.WEB_ANALYTICS:
            baseUrl = urls.webAnalytics()
            break
        case ProductKey.SESSION_REPLAY:
            baseUrl = urls.replay()
            break
        case ProductKey.FEATURE_FLAGS:
            baseUrl = urls.featureFlag('new')
            break
        case ProductKey.SURVEYS:
            baseUrl = urls.surveyTemplates()
            break
        case ProductKey.ERROR_TRACKING:
            baseUrl = urls.errorTracking()
            break
        case ProductKey.LLM_ANALYTICS:
            baseUrl = urls.llmAnalyticsDashboard()
            break
        default:
            baseUrl = urls.default()
    }

    // Append quickstart param to open the quick start popover after onboarding
    return `${baseUrl}?${QUICK_START_PARAM}=true`
}

export const onboardingLogic = kea<onboardingLogicType>([
    props({} as OnboardingLogicProps),
    path(['scenes', 'onboarding', 'onboardingLogic']),
    // connect this so we start collecting live events the whole time during onboarding
    connect(() => ({
        values: [
            billingLogic,
            ['billing'],
            teamLogic,
            ['currentTeam'],
            userLogic,
            ['user'],
            preflightLogic,
            ['isCloudOrDev'],
            sidePanelStateLogic,
            ['modalMode'],
        ],
        actions: [
            billingLogic,
            ['loadBillingSuccess'],
            teamLogic,
            ['updateCurrentTeam', 'updateCurrentTeamSuccess', 'recordProductIntentOnboardingComplete'],
            sidePanelStateLogic,
            ['openSidePanel'],
        ],
    })),
    actions({
        setProduct: (product: OnboardingProduct | null) => ({ product }),
        setProductKey: (productKey: ProductKey | null) => ({ productKey }),
        completeOnboarding: (options?: { redirectUrlOverride?: string }) => ({
            redirectUrlOverride: options?.redirectUrlOverride,
        }),
        setAllOnboardingSteps: (allOnboardingSteps: OnboardingStepElement[]) => ({ allOnboardingSteps }),
        setStepKey: (stepKey: OnboardingStepKey) => ({ stepKey }),
        setSubscribedDuringOnboarding: (subscribedDuringOnboarding: boolean) => ({ subscribedDuringOnboarding }),
        setTeamPropertiesForProduct: (productKey: ProductKey) => ({ productKey }),
        setWaitForBilling: (waitForBilling: boolean) => ({ waitForBilling }),
        goToNextStep: (numStepsToAdvance?: number) => ({ numStepsToAdvance }),
        goToPreviousStep: true,
        resetStepKey: true,
        setOnCompleteOnboardingRedirectUrl: (url: string | null) => ({ url }),
        skipOnboarding: true,
    }),
    reducers(() => ({
        productKey: [
            null as ProductKey | null,
            {
                setProductKey: (_, { productKey }) => productKey,
            },
        ],
        product: [
            null as OnboardingProduct | null,
            {
                setProduct: (_, { product }) => product ?? null,
            },
        ],
        allOnboardingSteps: [
            [] as OnboardingStepElement[],
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
        waitForBilling: [
            false,
            {
                setWaitForBilling: (_, { waitForBilling }) => waitForBilling,
            },
        ],
        onCompleteOnboardingRedirectUrlOverride: [
            null as string | null,
            {
                setOnCompleteOnboardingRedirectUrl: (_, { url }) => url,
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
                        name:
                            availableOnboardingProducts[productKey as keyof typeof availableOnboardingProducts]
                                ?.breadcrumbsName ??
                            availableOnboardingProducts[productKey as keyof typeof availableOnboardingProducts]?.name,
                        path: availableOnboardingProducts[productKey as keyof typeof availableOnboardingProducts]?.url,
                        iconType: 'action',
                    },
                    {
                        key: availableOnboardingProducts[productKey as keyof typeof availableOnboardingProducts]?.scene,
                        name: stepKeyToTitle(stepKey),
                        path: urls.onboarding({ productKey: productKey ?? undefined, stepKey }),
                        iconType: 'action',
                    },
                ]
            },
        ],
        onCompleteOnboardingRedirectUrl: [
            (s) => [s.productKey, s.onCompleteOnboardingRedirectUrlOverride],
            (productKey: string | null, onCompleteOnboardingRedirectUrlOverride) => {
                if (onCompleteOnboardingRedirectUrlOverride) {
                    return onCompleteOnboardingRedirectUrlOverride
                }
                return productKey ? getOnboardingCompleteRedirectUri(productKey as ProductKey) : urls.default()
            },
        ],
        totalOnboardingSteps: [
            (s) => [s.allOnboardingSteps],
            (allOnboardingSteps: OnboardingStepElement[]) => allOnboardingSteps.length,
        ],
        onboardingStepKeys: [
            (s) => [s.allOnboardingSteps],
            (allOnboardingSteps: OnboardingStepElement[]) => {
                return allOnboardingSteps.map(getStepKey)
            },
        ],
        currentOnboardingStep: [
            (s) => [s.allOnboardingSteps, s.stepKey],
            (allOnboardingSteps: OnboardingStepElement[], stepKey: OnboardingStepKey): OnboardingStepType | null =>
                allOnboardingSteps.find((step) => getStepKey(step) === stepKey) || null,
        ],
        hasNextStep: [
            (s) => [s.allOnboardingSteps, s.stepKey],
            (allOnboardingSteps: OnboardingStepElement[], stepKey: OnboardingStepKey) => {
                const currentStepIndex = allOnboardingSteps.findIndex((step) => getStepKey(step) === stepKey)
                return currentStepIndex < allOnboardingSteps.length - 1
            },
        ],
        hasPreviousStep: [
            (s) => [s.allOnboardingSteps, s.stepKey],
            (allOnboardingSteps: OnboardingStepElement[], stepKey: OnboardingStepKey) => {
                const currentStepIndex = allOnboardingSteps.findIndex((step) => getStepKey(step) === stepKey)
                return currentStepIndex > 0
            },
        ],
        shouldShowBillingStep: [
            (s) => [s.product, s.subscribedDuringOnboarding, s.isCloudOrDev, s.billing, s.billingProduct],
            (_product, subscribedDuringOnboarding: boolean, isCloudOrDev: boolean, billing, billingProduct) => {
                if (!isCloudOrDev || !billing?.products || !billingProduct) {
                    return false
                }

                return !billingProduct?.subscribed || subscribedDuringOnboarding
            },
        ],
        shouldShowReverseProxyStep: [
            (s) => [s.productKey],
            (productKey) => {
                return (
                    productKey && [ProductKey.FEATURE_FLAGS, ProductKey.EXPERIMENTS].includes(productKey as ProductKey)
                )
            },
        ],
        shouldShowDataWarehouseStep: [
            (s) => [s.productKey],
            (productKey) => {
                return productKey === ProductKey.PRODUCT_ANALYTICS
            },
        ],
        isStepKeyInvalid: [
            (s) => [s.stepKey, s.allOnboardingSteps, s.currentOnboardingStep],
            (
                stepKey: string,
                allOnboardingSteps: OnboardingStepElement[],
                currentOnboardingStep: React.ReactNode | null
            ) =>
                (stepKey && allOnboardingSteps.length > 0 && !currentOnboardingStep) ||
                (!stepKey && allOnboardingSteps.length > 0),
        ],
        billingProduct: [
            (s) => [s.product, s.productKey, s.billing],
            (_product, productKey, billing) => {
                return billing?.products?.find((p) => p.type === productKey)
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
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
                case ProductKey.LLM_ANALYTICS:
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
            actions.setProduct(availableOnboardingProducts[productKey])
        },
        setSubscribedDuringOnboarding: ({ subscribedDuringOnboarding }) => {
            if (subscribedDuringOnboarding) {
                // we might not have the product key yet
                // if not we'll just use the current url to determine the product key
                const productKey = values.productKey || (window.location.pathname.split('/')[2] as ProductKey)
                eventUsageLogic.actions.reportSubscribedDuringOnboarding(productKey)
            }
        },

        completeOnboarding: ({ redirectUrlOverride }) => {
            if (redirectUrlOverride) {
                actions.setOnCompleteOnboardingRedirectUrl(redirectUrlOverride)
            }
            if (values.productKey) {
                const productKey = values.productKey
                eventUsageLogic.actions.reportOnboardingCompleted(productKey)
                props.onCompleteOnboarding?.(productKey)
                actions.recordProductIntentOnboardingComplete({ product_type: productKey as ProductKey })
                teamLogic.actions.updateCurrentTeam({
                    has_completed_onboarding_for: {
                        ...values.currentTeam?.has_completed_onboarding_for,
                        [productKey]: true,
                    },
                })
            }
        },
        skipOnboarding: () => {
            router.actions.push(values.onCompleteOnboardingRedirectUrl)
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
            if (values.allOnboardingSteps.length > 0) {
                actions.setStepKey(getStepKey(values.allOnboardingSteps[0]))
            }
        },
    })),
    actionToUrl(({ actions, values }) => ({
        setStepKey: ({ stepKey }) => {
            if (stepKey) {
                return [`/onboarding/${values.productKey}`, { ...router.values.searchParams, step: stepKey }]
            }
            return [`/onboarding/${values.productKey}`, router.values.searchParams]
        },
        goToNextStep: ({ numStepsToAdvance }) => {
            const currentStepIndex = values.allOnboardingSteps.findIndex((step) => getStepKey(step) === values.stepKey)
            const nextStep = values.allOnboardingSteps[currentStepIndex + (numStepsToAdvance || 1)]
            if (nextStep) {
                return [
                    `/onboarding/${values.productKey}`,
                    { ...router.values.searchParams, step: getStepKey(nextStep) },
                ]
            }
            return [`/onboarding/${values.productKey}`, router.values.searchParams]
        },
        goToPreviousStep: () => {
            const currentStepIndex = values.allOnboardingSteps.findIndex((step) => getStepKey(step) === values.stepKey)
            const previousStep = values.allOnboardingSteps[currentStepIndex - 1]
            if (previousStep) {
                return [
                    `/onboarding/${values.productKey}`,
                    { ...router.values.searchParams, step: getStepKey(previousStep) },
                ]
            }
            return [`/onboarding/${values.productKey}`, router.values.searchParams]
        },
        updateCurrentTeamSuccess(val) {
            if (values.productKey && val.payload?.has_completed_onboarding_for?.[values.productKey]) {
                const redirectUrl = values.onCompleteOnboardingRedirectUrl
                actions.setOnCompleteOnboardingRedirectUrl(null)
                return [redirectUrl]
            }
        },
    })),
    urlToAction(({ actions, values }) => ({
        '/onboarding/:productKey': ({ productKey }, { success, upgraded, step }) => {
            if (!productKey || !(productKey in availableOnboardingProducts)) {
                return
            }

            if (success || upgraded) {
                actions.setSubscribedDuringOnboarding(true)
            }
            if (productKey !== values.productKey) {
                actions.setProductKey(productKey as ProductKey)
                // Reset onboarding steps so they can be populated upon render in the component.
                actions.setAllOnboardingSteps([])
            }

            if (step) {
                // when loading specific steps, like plans, we need to make sure we have a billing response before we can continue
                const stepsToWaitForBilling = [OnboardingStepKey.PLANS]
                if (stepsToWaitForBilling.includes(step as OnboardingStepKey)) {
                    actions.setWaitForBilling(true)
                }
                actions.setStepKey(step)
            } else {
                actions.resetStepKey()
            }
        },
        '/onboarding': () => {
            // Clear productKey when on the product selection page
            if (values.productKey !== null) {
                actions.setProductKey(null)
            }
        },
    })),
])
