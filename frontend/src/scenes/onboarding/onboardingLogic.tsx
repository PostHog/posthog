import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { liveEventsTableLogic } from 'scenes/activity/live/liveEventsTableLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Scene } from 'scenes/sceneTypes'
import { replayLandingPageLogic } from 'scenes/session-recordings/replayLandingPageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { Breadcrumb, OnboardingProduct, ProductKey, ReplayTabs } from '~/types'

import type { onboardingLogicType } from './onboardingLogicType'
import { availableOnboardingProducts } from './utils'

export interface OnboardingLogicProps {
    productKey: ProductKey | null
}

export enum OnboardingStepKey {
    PRODUCT_INTRO = 'product_intro',
    INSTALL = 'install',
    LINK_DATA = 'link_data',
    PLANS = 'plans',
    VERIFY = 'verify',
    PRODUCT_CONFIGURATION = 'configure',
    REVERSE_PROXY = 'proxy',
    INVITE_TEAMMATES = 'invite_teammates',
    DASHBOARD_TEMPLATE = 'dashboard_template',
    DASHBOARD_TEMPLATE_CONFIGURE = 'dashboard_template_configure',
    SESSION_REPLAY = 'session_replay',
    AUTHORIZED_DOMAINS = 'authorized_domains',
}

export const breadcrumbExcludeSteps = [OnboardingStepKey.DASHBOARD_TEMPLATE_CONFIGURE]

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

export const getProductUri = (productKey: ProductKey, replayLandingPage: ReplayTabs): string => {
    switch (productKey) {
        case ProductKey.PRODUCT_ANALYTICS:
            return urls.insightNew()
        case ProductKey.WEB_ANALYTICS:
            return urls.webAnalytics()
        case ProductKey.SESSION_REPLAY:
            return urls.replay(replayLandingPage)
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
    // connect this so we start collecting live events the whole time during onboarding
    connect(liveEventsTableLogic({ showLiveStreamErrorToast: false })),
    connect({
        values: [
            billingLogic,
            ['billing'],
            teamLogic,
            ['currentTeam'],
            userLogic,
            ['user'],
            preflightLogic,
            ['isCloudOrDev'],
            replayLandingPageLogic,
            ['replayLandingPage'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [
            billingLogic,
            ['loadBillingSuccess'],
            teamLogic,
            ['updateCurrentTeam', 'updateCurrentTeamSuccess', 'recordProductIntentOnboardingComplete'],
            sidePanelStateLogic,
            ['openSidePanel'],
        ],
    }),
    actions({
        setProduct: (product: OnboardingProduct | null) => ({ product }),
        setProductKey: (productKey: string | null) => ({ productKey }),
        completeOnboarding: (nextProductKey?: string, redirectUrlOverride?: string) => ({
            nextProductKey,
            redirectUrlOverride,
        }),
        setAllOnboardingSteps: (allOnboardingSteps: AllOnboardingSteps) => ({ allOnboardingSteps }),
        setStepKey: (stepKey: OnboardingStepKey) => ({ stepKey }),
        setSubscribedDuringOnboarding: (subscribedDuringOnboarding: boolean) => ({ subscribedDuringOnboarding }),
        setTeamPropertiesForProduct: (productKey: ProductKey) => ({ productKey }),
        setWaitForBilling: (waitForBilling: boolean) => ({ waitForBilling }),
        goToNextStep: (numStepsToAdvance?: number) => ({ numStepsToAdvance }),
        goToPreviousStep: true,
        resetStepKey: true,
        setOnCompleteOnboardingRedirectUrl: (url: string | null) => ({ url }),
    }),
    reducers(() => ({
        productKey: [
            null as string | null,
            {
                setProductKey: (_, { productKey }) => productKey,
            },
        ],
        product: [
            null as OnboardingProduct | null,
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
                    },
                    {
                        key: availableOnboardingProducts[productKey as keyof typeof availableOnboardingProducts]?.scene,
                        name: stepKeyToTitle(stepKey),
                        path: urls.onboarding(productKey ?? '', stepKey),
                    },
                ]
            },
        ],
        onCompleteOnboardingRedirectUrl: [
            (s) => [s.productKey, s.onCompleteOnboardingRedirectUrlOverride, s.replayLandingPage],
            (productKey: string | null, onCompleteOnboardingRedirectUrlOverride, replayLandingPage) => {
                if (onCompleteOnboardingRedirectUrlOverride) {
                    return onCompleteOnboardingRedirectUrlOverride
                }
                return productKey ? getProductUri(productKey as ProductKey, replayLandingPage) : urls.default()
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
            (s) => [s.productKey, s.featureFlags],
            (productKey, featureFlags) => {
                const dataWarehouseStepEnabled =
                    featureFlags[FEATURE_FLAGS.ONBOARDING_DATA_WAREHOUSE_FOR_PRODUCT_ANALYTICS] === 'test'

                if (!dataWarehouseStepEnabled) {
                    return false
                }

                return productKey === ProductKey.PRODUCT_ANALYTICS
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
        billingProduct: [
            (s) => [s.product, s.productKey, s.billing],
            (_product, productKey, billing) => {
                return billing?.products?.find((p) => p.type === productKey)
            },
        ],
    }),
    listeners(({ actions, values }) => ({
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

        completeOnboarding: ({ nextProductKey, redirectUrlOverride }) => {
            if (redirectUrlOverride) {
                actions.setOnCompleteOnboardingRedirectUrl(redirectUrlOverride)
            }
            if (values.productKey) {
                const productKey = values.productKey
                actions.recordProductIntentOnboardingComplete({ product_type: productKey as ProductKey })
                teamLogic.actions.updateCurrentTeam({
                    has_completed_onboarding_for: {
                        ...values.currentTeam?.has_completed_onboarding_for,
                        [productKey]: true,
                    },
                })
                if (nextProductKey) {
                    actions.setProductKey(nextProductKey)
                    router.actions.push(urls.onboarding(nextProductKey))
                }
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
            }
            return [`/onboarding/${values.productKey}`, router.values.searchParams]
        },
        goToNextStep: ({ numStepsToAdvance }) => {
            const currentStepIndex = values.allOnboardingSteps.findIndex(
                (step) => step.props.stepKey === values.stepKey
            )
            const nextStep = values.allOnboardingSteps[currentStepIndex + (numStepsToAdvance || 1)]
            if (nextStep) {
                return [
                    `/onboarding/${values.productKey}`,
                    { ...router.values.searchParams, step: nextStep.props.stepKey },
                ]
            }
            return [`/onboarding/${values.productKey}`, router.values.searchParams]
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
            }
            return [`/onboarding/${values.productKey}`, router.values.searchParams]
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
                // when loading specific steps, like plans, we need to make sure we have a billing response before we can continue
                const stepsToWaitForBilling = [OnboardingStepKey.PLANS, OnboardingStepKey.PRODUCT_INTRO]
                if (stepsToWaitForBilling.includes(step as OnboardingStepKey)) {
                    actions.setWaitForBilling(true)
                }
                actions.setStepKey(step)
            } else {
                actions.resetStepKey()
            }
        },
    })),
])
