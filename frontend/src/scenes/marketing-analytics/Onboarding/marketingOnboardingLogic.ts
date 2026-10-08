import { MakeLogicType, actions, kea, listeners, path, reducers } from 'kea'

import { MARKETING_ONBOARDING_STORAGE_KEYS } from './constants'

export type marketingOnboardingLogicType = MakeLogicType<
    { showOnboarding: boolean; showManualSources: boolean; manualSourceSearch: string },
    {
        setManualSourceSearch: (search: string) => { search: string }
        completeOnboarding: () => { value: true }
        resetOnboarding: () => { value: true }
        setShowOnboarding: (show: boolean) => { show: boolean }
        setShowManualSources: (show: boolean) => { show: boolean }
    }
>

export const marketingOnboardingLogic = kea<marketingOnboardingLogicType>([
    path(['scenes', 'marketing-analytics', 'Onboarding', 'marketingOnboardingLogic']),
    actions({
        setManualSourceSearch: (search: string) => ({ search }),
        completeOnboarding: true,
        resetOnboarding: true,
        setShowOnboarding: (show: boolean) => ({ show }),
        setShowManualSources: (show: boolean) => ({ show }),
    }),
    reducers({
        manualSourceSearch: ['', { setManualSourceSearch: (_, { search }) => search, resetOnboarding: () => '' }],
        showOnboarding: [
            localStorage.getItem(MARKETING_ONBOARDING_STORAGE_KEYS.COMPLETED) !== 'true',
            { setShowOnboarding: (_, { show }) => show, completeOnboarding: () => false, resetOnboarding: () => true },
        ],
        showManualSources: [
            false,
            {
                setShowManualSources: (_, { show }) => show,
                resetOnboarding: () => false,
                completeOnboarding: () => false,
            },
        ],
    }),
    listeners({
        completeOnboarding: () => {
            localStorage.setItem(MARKETING_ONBOARDING_STORAGE_KEYS.COMPLETED, 'true')
            localStorage.removeItem(MARKETING_ONBOARDING_STORAGE_KEYS.STEP)
        },
        resetOnboarding: () => {
            localStorage.removeItem(MARKETING_ONBOARDING_STORAGE_KEYS.COMPLETED)
            localStorage.removeItem(MARKETING_ONBOARDING_STORAGE_KEYS.STEP)
        },
    }),
])
