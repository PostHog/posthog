import { kea } from 'kea'
import { Framework, PlatformType } from 'scenes/ingestion/types'
import { ingestionLogicType } from 'types/scenes/ingestion/ingestionLogicType'
import { API, MOBILE, WEB } from 'scenes/ingestion/constants'
import { userLogic } from 'scenes/userLogic'
import { router } from 'kea-router'

export const ingestionLogic = kea<ingestionLogicType<PlatformType, Framework>>({
    actions: {
        setPlatform: (platform: PlatformType) => ({ platform }),
        setCustomEvent: (customEvent: boolean) => ({ customEvent }),
        setFramework: (framework: Framework) => ({ framework: framework as Framework }),
        setVerify: (verify: boolean) => ({ verify }),
        setState: (platform: PlatformType, customEvent: boolean, framework: string | null, verify: boolean) => ({
            platform,
            customEvent,
            framework,
            verify,
        }),
        completeOnboarding: true,
    },

    reducers: {
        platform: [
            null as null | PlatformType,
            {
                setPlatform: (_, { platform }) => platform,
                setCustomEvent: () => WEB,
                setState: (_, { platform }) => platform,
            },
        ],
        customEvent: [
            false,
            {
                setPlatform: () => false,
                setCustomEvent: (_, { customEvent }) => customEvent,
                setState: (_, { customEvent }) => customEvent,
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
                setCustomEvent: () => false,
                setFramework: () => false,
                setVerify: (_, { verify }) => verify,
                setState: (_, { verify }) => verify,
            },
        ],
    },

    selectors: {
        index: [
            (s) => [s.platform, s.customEvent, s.framework, s.verify],
            (platform, customEvent, framework, verify) => {
                return (verify ? 1 : 0) + (framework ? 1 : 0) + (platform ? 1 : 0) + (customEvent ? 1 : 0)
            },
        ],
        totalSteps: [
            (s) => [s.platform, s.framework, s.customEvent, s.verify],
            (platform, framework, customEvent, verify) => {
                // if missing parts of the URL
                if (verify) {
                    return 5 - (platform ? 0 : 1) - (framework ? 0 : 1) - (customEvent ? 0 : 1)
                }
                if (framework === API && !platform) {
                    return 4 - (customEvent ? 0 : 1)
                }

                return platform === WEB && !customEvent ? 3 : platform === MOBILE ? 4 : 5
            },
        ],
    },

    actionToUrl: ({ values }) => ({
        setPlatform: () => getUrl(values),
        setCustomEvent: () => getUrl(values),
        setFramework: () => getUrl(values),
        setVerify: () => getUrl(values),
    }),

    urlToAction: ({ actions }) => ({
        '/ingestion': () => actions.setState(null, false, null, false),
        '/ingestion/verify': (_: any, { platform, framework }: Record<string, string>) => {
            actions.setState(
                platform === 'mobile' ? MOBILE : platform === 'web' || platform === 'web-custom' ? WEB : null,
                platform === 'web-custom',
                framework,
                true
            )
        },
        '/ingestion/api': (_: any, { platform }: Record<string, string>) => {
            actions.setState(
                platform === 'mobile' ? MOBILE : platform === 'web' || platform === 'web-custom' ? WEB : null,
                platform === 'web-custom',
                API,
                false
            )
        },
        '/ingestion(/:platform)(/:framework)': ({ platform, framework }: Record<string, string>) => {
            actions.setState(
                platform === 'mobile' ? MOBILE : platform === 'web' || platform === 'web-custom' ? WEB : null,
                platform === 'web-custom',
                framework,
                false
            )
        },
    }),

    listeners: () => ({
        completeOnboarding: () => {
            const { user } = userLogic.values
            if (user) {
                // make the change immediately before the request comes back
                // this way we are not re-redirected to the ingestion page
                userLogic.actions.setUser({
                    ...user,
                    team: {
                        ...user.team,
                        completed_snippet_onboarding: true,
                    },
                })
            }
            userLogic.actions.userUpdateRequest({ team: { completed_snippet_onboarding: true } })
            router.actions.push('/insights')
        },
    }),
})

function getUrl(values: typeof ingestionLogic['values']): string | [string, Record<string, undefined | string>] {
    const { platform, framework, customEvent, verify } = values

    let url = '/ingestion'

    if (verify) {
        url += '/verify'
        return [
            url,
            {
                platform:
                    platform === WEB
                        ? customEvent
                            ? 'web-custom'
                            : 'web'
                        : platform === MOBILE
                        ? 'mobile'
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
                        ? customEvent
                            ? 'web-custom'
                            : 'web'
                        : platform === MOBILE
                        ? 'mobile'
                        : undefined,
            },
        ]
    }

    if (platform === MOBILE) {
        url += '/mobile'
    }

    if (platform === WEB) {
        url += '/web'
        if (customEvent) {
            url += '-custom'
        }
    }

    if (framework) {
        url += `/${framework.toLowerCase()}`
    }

    return url
}
