import { kea } from 'kea'
import { Framework, PlatformType } from 'scenes/ingestion/types'
import { API, MOBILE, BACKEND, WEB, BOOKMARKLET } from 'scenes/ingestion/constants'
import { ingestionLogicType } from './ingestionLogicType'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

export const ingestionLogic = kea<ingestionLogicType>({
    path: ['scenes', 'ingestion', 'ingestionLogic'],
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
                if (verify) {
                    return 3
                }
                if (platform === WEB || platform === BOOKMARKLET) {
                    return 2
                }
                return (verify ? 1 : 0) + (framework ? 1 : 0) + (platform ? 1 : 0)
            },
        ],
        onboarding1: [
            () => [],
            (): boolean => {
                const featFlags = featureFlagLogic.values.featureFlags
                return !!featFlags[FEATURE_FLAGS.ONBOARDING_1]
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
                platform === 'mobile'
                    ? MOBILE
                    : platform === 'web'
                    ? WEB
                    : platform === 'backend'
                    ? BACKEND
                    : platform === 'just-exploring'
                    ? BOOKMARKLET
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
                    : null,
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
            window.location.href = '/'
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
                        : platform === BOOKMARKLET
                        ? 'just-exploring'
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

    if (framework) {
        url += `/${framework.toLowerCase()}`
    }

    return url
}
