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
import { FEATURE_FLAGS } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'
import { PluginTypeWithConfig } from 'scenes/plugins/types'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'
import { actionToUrl, router, urlToAction } from 'kea-router'

export const ingestionLogic = kea<ingestionLogicType>([
    path(['scenes', 'ingestion', 'ingestionLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
        actions: [teamLogic, ['updateCurrentTeamSuccess']],
    }),
    actions({
        setPlatform: (platform: PlatformType) => ({ platform }),
        setFramework: (framework: Framework) => ({ framework: framework as Framework }),
        setVerify: (verify: boolean) => ({ verify }),
        setState: (platform: PlatformType, framework: string | null, verify: boolean) => ({
            platform,
            framework,
            verify,
        }),
        setActiveTab: (tab: string) => ({ tab }),
        setInstructionsModal: (isOpen: boolean) => ({ isOpen }),
        setThirdPartySource: (sourceIndex: number) => ({ sourceIndex }),
        openThirdPartyPluginModal: (plugin: PluginTypeWithConfig) => ({ plugin }),
        setIndex: (index: number) => ({ index }),
        completeOnboarding: true,
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
                setVerify: (_, { verify }) => verify,
                setState: (_, { verify }) => verify,
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
                setIndex: (_, { index }) => index,
                setPlatform: (state, { platform }) => (platform ? 1 : Math.max(state - 1, 0)),
                setFramework: (state, { framework }) => (framework ? 1 : Math.max(state - 1, 0)),
                setVerify: () => 2,
                setState: (_, { platform, framework, verify }) => {
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

    selectors(({ values }) => ({
        index: [
            (s) => [s.platform, s.framework, s.verify],
            (platform, framework, verify) => {
                if (verify) {
                    return 3
                }
                if (platform === WEB || platform === BOOKMARKLET || platform === THIRD_PARTY) {
                    return 2
                }
                return (verify ? 1 : 0) + (framework ? 1 : 0) + (platform ? 1 : 0)
            },
        ],
        onboarding1: [
            () => [],
            (): boolean => {
                const featFlags = values.featureFlags
                return featFlags[FEATURE_FLAGS.ONBOARDING_1] === 'test'
            },
        ],
        onboardingSidebarEnabled: [
            () => [],
            (): boolean => {
                // DO NOT MAKE A FEATURE FLAG OUT OF THIS ON CLOUD IT'S PART OF EXPERIMENTS
                return !!values.featureFlags[FEATURE_FLAGS.ONBOARDING_1_5]
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
        updateCurrentTeamSuccess: () => {
            if (router.values.location.pathname == '/ingestion/verify') {
                return urls.events()
            }
        },
    })),

    urlToAction(({ actions }) => ({
        '/ingestion': () => actions.setState(null, null, false),
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
                true
            )
        },
        '/ingestion/api': (_: any, { platform }) => {
            actions.setState(
                platform === 'mobile' ? MOBILE : platform === 'web' ? WEB : platform === 'backend' ? BACKEND : null,
                API,
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
                false
            )
        },
    })),
    listeners(() => ({
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
    })),
])

function getUrl(values: ingestionLogicType['values']): string | [string, Record<string, undefined | string>] {
    const { platform, framework, verify } = values

    let url = '/ingestion'

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
