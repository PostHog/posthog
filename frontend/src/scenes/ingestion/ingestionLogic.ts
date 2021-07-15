import { kea } from 'kea'
import { Framework, PlatformType } from 'scenes/ingestion/types'
import { API, MOBILE, BACKEND, WEB } from 'scenes/ingestion/constants'
import { ingestionLogicType } from './ingestionLogicType'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

export const ingestionLogic = kea<ingestionLogicType>({
    connect: {
        actions: [teamLogic, ['updateCurrentTeamSuccess']],
    },
    actions: {
        setPlatform: (platform: PlatformType) => ({ platform }),
        setFramework: (framework: Framework) => ({ framework: framework as Framework }),
        setVerify: (verify: boolean) => ({ verify }),
        setState: (platform: PlatformType, framework: string | null, verify: boolean) => ({
            platform,
            framework,
            verify,
        }),
        setActiveTab: (tab: string) => ({ tab }),
        completeOnboarding: true,
    },

    reducers: {
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
    },

    selectors: {
        index: [
            (s) => [s.platform, s.framework, s.verify],
            (platform, framework, verify) => {
                const featFlags = featureFlagLogic.values.featureFlags
                if (featFlags[FEATURE_FLAGS.INGESTION_GRID]) {
                    return (framework && platform ? 1 : 0) + (verify ? 1 : 0)
                }
                return (verify ? 1 : 0) + (framework ? 1 : 0) + (platform ? 1 : 0)
            },
        ],
        totalSteps: [
            (s) => [s.platform, s.framework, s.verify],
            (platform, framework, verify) => {
                const featFlags = featureFlagLogic.values.featureFlags
                if (featFlags[FEATURE_FLAGS.INGESTION_GRID]) {
                    return 3
                }
                // if missing parts of the URL
                if (verify) {
                    return 4 - (platform ? 0 : 1) - (framework ? 0 : 1)
                }
                if (framework === API && !platform) {
                    return 4
                }

                return platform === WEB ? 3 : 4 // (mobile & backend)
            },
        ],
    },

    actionToUrl: ({ values }) => ({
        setPlatform: () => getUrl(values),
        setFramework: () => getUrl(values),
        setVerify: () => getUrl(values),
    }),

    urlToAction: ({ actions }) => ({
        '/ingestion': () => actions.setState(null, null, false),
        '/ingestion/verify': (_: any, { platform, framework }) => {
            actions.setState(
                platform === 'mobile' ? MOBILE : platform === 'web' ? WEB : platform === 'backend' ? BACKEND : null,
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
                platform === 'mobile' ? MOBILE : platform === 'web' ? WEB : platform === 'backend' ? BACKEND : null,
                framework as Framework,
                false
            )
        },
    }),

    listeners: () => ({
        completeOnboarding: () => {
            teamLogic.actions.updateCurrentTeam({
                completed_snippet_onboarding: true,
            })
        },
        updateCurrentTeamSuccess: () => {
            const usingOnboardingSetup = organizationLogic.values.currentOrganization?.setup.is_active
            // If user is under the new setup state (#2822), take them back to start section II of the setup
            window.location.href = usingOnboardingSetup ? '/setup' : '/'
        },
    }),
})

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

    if (framework) {
        url += `/${framework.toLowerCase()}`
    }

    return url
}
