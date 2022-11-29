import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { Framework, PlatformType } from 'scenes/ingestion/v1/types'
import {
    API,
    MOBILE,
    BACKEND,
    WEB,
    BOOKMARKLET,
    thirdPartySources,
    THIRD_PARTY,
    ThirdPartySource,
} from 'scenes/ingestion/v1/constants'
import type { ingestionLogicType } from './ingestionLogicType'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { PluginTypeWithConfig } from 'scenes/plugins/types'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { getBreakpoint } from 'lib/utils/responsiveUtils'
import { windowValues } from 'kea-window-values'
import { billingLogic } from 'scenes/billing/billingLogic'
import { subscriptions } from 'kea-subscriptions'
import { BillingType, TeamType } from '~/types'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

export enum INGESTION_STEPS {
    START = 'Get started',
    CONNECT_PRODUCT = 'Connect your product',
    VERIFY = 'Listen for events',
    BILLING = 'Add payment method',
    DONE = 'Done!',
}

export enum INGESTION_STEPS_WITHOUT_BILLING {
    START = 'Get started',
    CONNECT_PRODUCT = 'Connect your product',
    VERIFY = 'Listen for events',
    DONE = 'Done!',
}

export const ingestionLogic = kea<ingestionLogicType>([
    path(['scenes', 'ingestion', 'ingestionLogic']),
    connect({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            billingLogic,
            ['billing'],
            teamLogic,
            ['currentTeam'],
            preflightLogic,
            ['preflight'],
        ],
        actions: [teamLogic, ['updateCurrentTeamSuccess']],
    }),
    actions({
        setPlatform: (platform: PlatformType) => ({ platform }),
        setFramework: (framework: Framework) => ({ framework: framework as Framework }),
        setVerify: (verify: boolean) => ({ verify }),
        setAddBilling: (addBilling: boolean) => ({ addBilling }),
        setState: (platform: PlatformType, framework: string | null, verify: boolean, addBilling: boolean) => ({
            platform,
            framework,
            verify,
            addBilling,
        }),
        setActiveTab: (tab: string) => ({ tab }),
        setInstructionsModal: (isOpen: boolean) => ({ isOpen }),
        setThirdPartySource: (sourceIndex: number) => ({ sourceIndex }),
        openThirdPartyPluginModal: (plugin: PluginTypeWithConfig) => ({ plugin }),
        completeOnboarding: true,
        setCurrentStep: (currentStep: string) => ({ currentStep }),
        sidebarStepClick: (step: string) => ({ step }),
        onBack: true,
        setSidebarSteps: (steps: string[]) => ({ steps }),
    }),
    windowValues({
        isSmallScreen: (window: Window) => window.innerWidth < getBreakpoint('md'),
    }),
    reducers({
        platform: [
            null as null | PlatformType,
            {
                setPlatform: (_, { platform }) => platform,
                setState: (_, { platform }) => platform,
            },
        ],
        framework: [
            null as null | Framework,
            {
                setFramework: (_, { framework }) => framework as Framework,
                setState: (_, { framework }) => (framework ? (framework.toUpperCase() as Framework) : null),
            },
        ],
        verify: [
            false,
            {
                setPlatform: () => false,
                setFramework: () => false,
                setAddBilling: () => false,
                setVerify: (_, { verify }) => verify,
                setState: (_, { verify }) => verify,
            },
        ],
        addBilling: [
            false,
            {
                setPlatform: () => false,
                setFramework: () => false,
                setVerify: () => false,
                setAddBilling: (_, { addBilling }) => addBilling,
                setState: (_, { addBilling }) => addBilling,
            },
        ],
        activeTab: [
            'browser',
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        instructionsModalOpen: [
            false as boolean,
            {
                setInstructionsModal: (_, { isOpen }) => isOpen,
                openThirdPartyPluginModal: () => true,
            },
        ],
        thirdPartyIntegrationSource: [
            null as ThirdPartySource | null,
            {
                setThirdPartySource: (_, { sourceIndex }) => thirdPartySources[sourceIndex],
            },
        ],
        thirdPartyPluginSource: [
            null as PluginTypeWithConfig | null,
            {
                openThirdPartyPluginModal: (_, { plugin }) => plugin,
            },
        ],
        sidebarSteps: [
            Object.values(INGESTION_STEPS_WITHOUT_BILLING) as string[],
            {
                setSidebarSteps: (_, { steps }) => steps,
            },
        ],
    }),
    selectors(() => ({
        currentStep: [
            (s) => [s.platform, s.framework, s.verify, s.addBilling],
            (platform, framework, verify, addBilling) => {
                if (addBilling) {
                    return INGESTION_STEPS.BILLING
                }
                if (verify) {
                    return INGESTION_STEPS.VERIFY
                }
                if (platform || framework) {
                    return INGESTION_STEPS.CONNECT_PRODUCT
                }
                return INGESTION_STEPS.START
            },
        ],
        previousStep: [
            (s) => [s.currentStep],
            (currentStep) => {
                const currentStepIndex = Object.values(INGESTION_STEPS).indexOf(currentStep)
                return Object.values(INGESTION_STEPS)[currentStepIndex - 1]
            },
        ],
        frameworkString: [
            (s) => [s.framework],
            (framework): string => {
                if (framework) {
                    const frameworkStrings = {
                        NODEJS: 'Node.js',
                        GO: 'Go',
                        RUBY: 'Ruby',
                        PYTHON: 'Python',
                        PHP: 'PHP',
                        ELIXIR: 'Elixir',
                        ANDROID: 'Android',
                        IOS: 'iOS',
                        REACT_NATIVE: 'React Native',
                        FLUTTER: 'Flutter',
                        API: 'HTTP API',
                    }
                    return frameworkStrings[framework] || framework
                }
                return ''
            },
        ],
        showBillingStep: [
            (s) => [s.preflight],
            (preflight): boolean => {
                return !!preflight?.cloud && !preflight?.demo
            },
        ],
    })),

    actionToUrl(({ values }) => ({
        setPlatform: () => getUrl(values),
        setFramework: () => getUrl(values),
        setVerify: () => getUrl(values),
        setAddBilling: () => getUrl(values),
        setState: () => getUrl(values),
        updateCurrentTeamSuccess: () => {
            const isBillingPage = router.values.location.pathname == '/ingestion/billing'
            const isVerifyPage = !values.showBillingStep && router.values.location.pathname == '/ingestion/verify'
            if (isBillingPage || isVerifyPage) {
                return urls.events()
            }
        },
    })),

    urlToAction(({ actions }) => ({
        '/ingestion': () => actions.setState(null, null, false, false),
        '/ingestion/billing': (_: any, { platform, framework }) => {
            actions.setState(
                platform === 'mobile'
                    ? MOBILE
                    : platform === 'web'
                    ? WEB
                    : platform === 'backend'
                    ? BACKEND
                    : platform === 'just-exploring'
                    ? BOOKMARKLET
                    : platform === 'third-party'
                    ? THIRD_PARTY
                    : null,
                framework,
                false,
                true
            )
        },
        '/ingestion/verify': (_: any, { platform, framework }) => {
            actions.setState(
                platform === 'mobile'
                    ? MOBILE
                    : platform === 'web'
                    ? WEB
                    : platform === 'backend'
                    ? BACKEND
                    : platform === 'just-exploring'
                    ? BOOKMARKLET
                    : platform === 'third-party'
                    ? THIRD_PARTY
                    : null,
                framework,
                true,
                false
            )
        },
        '/ingestion/api': (_: any, { platform }) => {
            actions.setState(
                platform === 'mobile' ? MOBILE : platform === 'web' ? WEB : platform === 'backend' ? BACKEND : null,
                API,
                false,
                false
            )
        },
        '/ingestion(/:platform)(/:framework)': ({ platform, framework }) => {
            actions.setState(
                platform === 'mobile'
                    ? MOBILE
                    : platform === 'web'
                    ? WEB
                    : platform === 'backend'
                    ? BACKEND
                    : platform === 'just-exploring'
                    ? BOOKMARKLET
                    : platform === 'third-party'
                    ? THIRD_PARTY
                    : null,
                framework as Framework,
                false,
                false
            )
        },
    })),
    listeners(({ actions, values }) => ({
        completeOnboarding: () => {
            teamLogic.actions.updateCurrentTeam({
                completed_snippet_onboarding: true,
            })
        },
        openThirdPartyPluginModal: ({ plugin }) => {
            pluginsLogic.actions.editPlugin(plugin.id)
        },
        setPlatform: ({ platform }) => {
            eventUsageLogic.actions.reportIngestionSelectPlatformType(platform)
        },
        setFramework: ({ framework }) => {
            eventUsageLogic.actions.reportIngestionSelectFrameworkType(framework)
        },
        sidebarStepClick: ({ step }) => {
            switch (step) {
                case INGESTION_STEPS.START:
                    actions.setPlatform(null)
                    return
                case INGESTION_STEPS.CONNECT_PRODUCT:
                    if (values.platform) {
                        actions.setVerify(false)
                        actions.setPlatform(values.platform)
                    }
                    return
                case INGESTION_STEPS.VERIFY:
                    if (values.platform) {
                        actions.setVerify(true)
                    }
                    return
                case INGESTION_STEPS.BILLING:
                    if (values.platform) {
                        actions.setAddBilling(true)
                    }
                    return
                default:
                    return
            }
        },
        onBack: () => {
            switch (values.currentStep) {
                case INGESTION_STEPS.BILLING:
                    actions.setState(values.platform, values.framework, true, false)
                    return
                case INGESTION_STEPS.VERIFY:
                    actions.setState(values.platform, null, false, false)
                    return
                case INGESTION_STEPS.CONNECT_PRODUCT:
                    actions.setState(null, null, false, false)
                    return
                default:
                    return
            }
        },
    })),
    subscriptions(({ actions, values }) => ({
        showBillingStep: (value) => {
            const steps = value ? INGESTION_STEPS : INGESTION_STEPS_WITHOUT_BILLING
            actions.setSidebarSteps(Object.values(steps))
        },
        billing: (billing: BillingType) => {
            if (billing?.plan && values.addBilling) {
                actions.setCurrentStep(INGESTION_STEPS.DONE)
            }
        },
        currentTeam: (currentTeam: TeamType) => {
            if (currentTeam?.ingested_event && values.verify && !values.showBillingStep) {
                actions.setCurrentStep(INGESTION_STEPS.DONE)
            }
        },
    })),
])

function getUrl(values: ingestionLogicType['values']): string | [string, Record<string, undefined | string>] {
    const { platform, framework, verify, addBilling } = values

    let url = '/ingestion'

    if (addBilling) {
        return url + '/billing'
    }

    if (verify) {
        url += '/verify'
        return [
            url,
            {
                platform:
                    platform === WEB
                        ? 'web'
                        : platform === MOBILE
                        ? 'mobile'
                        : platform === BACKEND
                        ? 'backend'
                        : platform === BOOKMARKLET
                        ? 'just-exploring'
                        : platform === THIRD_PARTY
                        ? 'third-party'
                        : undefined,
                framework: framework?.toLowerCase() || undefined,
            },
        ]
    }

    if (framework === API) {
        url += '/api'
        return [
            url,
            {
                platform:
                    platform === WEB
                        ? 'web'
                        : platform === MOBILE
                        ? 'mobile'
                        : platform === BACKEND
                        ? 'backend'
                        : undefined,
            },
        ]
    }

    if (platform === MOBILE) {
        url += '/mobile'
    }

    if (platform === WEB) {
        url += '/web'
    }

    if (platform === BACKEND) {
        url += '/backend'
    }

    if (platform === BOOKMARKLET) {
        url += '/just-exploring'
    }

    if (platform === THIRD_PARTY) {
        url += '/third-party'
    }

    if (framework) {
        url += `/${framework.toLowerCase()}`
    }

    return url
}
