import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { Framework, PlatformType } from 'scenes/ingestion/types'
import {
    API,
    MOBILE,
    BACKEND,
    WEB,
    BOOKMARKLET,
    thirdPartySources,
    THIRD_PARTY,
    ThirdPartySource,
} from 'scenes/ingestion/constants'
import type { ingestionLogicType } from './ingestionLogicType'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { PluginTypeWithConfig } from 'scenes/plugins/types'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { getBreakpoint } from 'lib/utils/responsiveUtils'
import { windowValues } from 'kea-window-values'
import { billingLogic } from 'scenes/billing/billingLogic'

export const STEPS = ['Get started', 'Connect your product', 'Listen for events', 'Done!']

export const STEPS_WITH_BILLING = [
    'Get started',
    'Connect your product',
    'Listen for events',
    'Add payment method',
    'Done!',
]

export const ingestionLogic = kea<ingestionLogicType>([
    path(['scenes', 'ingestion', 'ingestionLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags'], billingLogic, ['billing'], teamLogic, ['currentTeam']],
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
        setCurrentIndex: (currentIndex: number) => ({ currentIndex }),
        sidebarStepClick: (index: number) => ({ index }),
        onBack: true,
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
        currentIndex: [
            0,
            {
                setCurrentIndex: (_, { currentIndex }) => currentIndex,
                setPlatform: (state, { platform }) => (platform ? 1 : Math.max(state - 1, 0)),
                setFramework: (state, { framework }) => (framework ? 1 : Math.max(state - 1, 0)),
                setVerify: () => 2,
                setAddBilling: () => 3,
                setState: (_, { platform, framework, verify, addBilling }) => {
                    if (addBilling) {
                        return 3
                    }
                    if (verify) {
                        return 2
                    }
                    if (platform || framework) {
                        return 1
                    }
                    return 0
                },
            },
        ],
    }),
    selectors(() => ({
        index: [
            (s) => [s.platform, s.framework, s.verify, s.addBilling],
            (platform, framework, verify, addBilling) => {
                if (addBilling) {
                    return 3
                }
                if (verify) {
                    return 2
                }
                if (platform === WEB || platform === BOOKMARKLET || platform === THIRD_PARTY) {
                    return 1
                }
                return (verify ? 1 : 0) + (framework ? 1 : 0) + (platform ? 1 : 0)
            },
        ],
        previousStepName: [
            (s) => [s.index],
            (index) => {
                return STEPS[index > 0 ? index - 1 : 0]
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
    })),

    actionToUrl(({ values }) => ({
        setPlatform: () => getUrl(values),
        setFramework: () => getUrl(values),
        setVerify: () => getUrl(values),
        setAddBilling: () => getUrl(values),
        updateCurrentTeamSuccess: () => {
            if (router.values.location.pathname == '/ingestion/verify') {
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
        sidebarStepClick: ({ index }) => {
            switch (index) {
                case 0:
                    actions.setPlatform(null)
                    return
                case 1:
                    if (values.platform) {
                        actions.setVerify(false)
                        actions.setPlatform(values.platform)
                    }
                    return
                case 2:
                    if (values.platform) {
                        actions.setVerify(true)
                    }
                    return
                case 3:
                    if (values.platform) {
                        actions.setAddBilling(true)
                    }
                    return
                default:
                    return
            }
        },
        onBack: () => {
            switch (values.index) {
                case 3:
                    actions.setState(values.platform, values.framework, true, false)
                    return
                case 2:
                    actions.setState(values.platform, null, false, false)
                    return
                case 1:
                    actions.setState(null, null, false, false)
                    return
                default:
                    return
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
