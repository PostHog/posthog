import { kea } from 'kea'
import { Framework, PlatformType } from 'scenes/onboarding/types'
import { onboardingLogicType } from 'types/scenes/onboarding/onboardingLogicType'
import { MOBILE, WEB } from 'scenes/onboarding/constants'
import { userLogic } from 'scenes/userLogic'
import { router } from 'kea-router'

export const onboardingLogic = kea<onboardingLogicType<PlatformType, Framework>>({
    actions: {
        setPlatformType: (type: PlatformType) => ({ type }),
        setCustomEvent: (customEvent: boolean) => ({ customEvent }),
        setFramework: (framework: Framework) => ({ framework: framework as Framework }),
        setVerify: (verify: boolean) => ({ verify }),
        setState: (type: PlatformType, customEvent: boolean, framework: string | null, verify: boolean) => ({
            type,
            customEvent,
            framework,
            verify,
        }),
        completeOnboarding: true,
    },

    reducers: {
        platformType: [
            null as null | PlatformType,
            { setPlatformType: (_, { type }) => type, setCustomEvent: () => WEB, setState: (_, { type }) => type },
        ],
        customEvent: [
            false,
            {
                setPlatformType: () => false,
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
                setPlatformType: () => false,
                setCustomEvent: () => false,
                setFramework: () => false,
                setVerify: (_, { verify }) => verify,
                setState: (_, { verify }) => verify,
            },
        ],
    },

    selectors: {
        index: [
            (s) => [s.platformType, s.customEvent, s.framework, s.verify],
            (platformType, customEvent, framework, verify) => {
                return (verify ? 1 : 0) + (framework ? 1 : 0) + (platformType ? 1 : 0) + (customEvent ? 1 : 0)
            },
        ],
        totalSteps: [
            (s) => [s.platformType, s.customEvent],
            (platformType, customEvent) => {
                if (platformType === WEB && !customEvent) {
                    return 3
                }
                if (platformType === MOBILE) {
                    return 4
                }
                return 5
            },
        ],
    },

    actionToUrl: ({ values }) => ({
        setPlatformType: () => getUrl(values),
        setCustomEvent: () => getUrl(values),
        setFramework: () => getUrl(values),
        setVerify: () => getUrl(values),
    }),

    urlToAction: ({ actions }) => ({
        '/onboarding': () => actions.setState(null, false, null, false),
        '/onboarding(/:type)(/:framework)(/:verify)': ({ type, framework, verify }: Record<string, string>) => {
            actions.setState(
                type === 'mobile' ? MOBILE : type === 'web' || type === 'web-custom' ? WEB : null,
                type === 'web-custom',
                framework === 'verify' ? null : framework,
                !!verify || framework === 'verify'
            )
        },
    }),

    listeners: () => ({
        completeOnboarding: () => {
            userLogic.actions.userUpdateRequest({ team: { completed_snippet_onboarding: true } })
            router.actions.push('/insights')
        },
    }),
})

function getUrl(values: typeof onboardingLogic['values']): string {
    const { platformType, framework, customEvent, verify } = values

    let url = '/onboarding'

    if (platformType === MOBILE) {
        url += '/mobile'
    }

    if (platformType === WEB) {
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
