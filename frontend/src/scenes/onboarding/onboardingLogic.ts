import { kea } from 'kea'
import { Framework, PlatformType } from 'scenes/onboarding/types'
import { onboardingLogicType } from 'types/scenes/onboarding/onboardingLogicType'
import { MOBILE, WEB } from 'scenes/onboarding/constants'
import { userLogic } from 'scenes/userLogic'
import { router } from 'kea-router'

export const onboardingLogic = kea<onboardingLogicType<PlatformType, Framework>>({
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
            (s) => [s.platform, s.customEvent],
            (platform, customEvent) => {
                if (platform === WEB && !customEvent) {
                    return 3
                }
                if (platform === MOBILE) {
                    return 4
                }
                return 5
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
        '/onboarding': () => actions.setState(null, false, null, false),
        '/onboarding(/:platform)(/:framework)(/:verify)': ({ platform, framework, verify }: Record<string, string>) => {
            actions.setState(
                platform === 'mobile' ? MOBILE : platform === 'web' || platform === 'web-custom' ? WEB : null,
                platform === 'web-custom',
                framework === 'verify' ? null : framework,
                !!verify || framework === 'verify'
            )
        },
    }),

    listeners: () => ({
        completeOnboarding: () => {
            const { user } = userLogic.values
            if (user) {
                // make the change immediately before the request comes back
                // this way we are not re-redirected to the onboarding page
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

function getUrl(values: typeof onboardingLogic['values']): string | [string, Record<string, boolean | string | null>] {
    const { platform, framework, customEvent, verify } = values

    let url = '/onboarding'

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

    if (verify) {
        url += '/verify'
    }

    return url
}
