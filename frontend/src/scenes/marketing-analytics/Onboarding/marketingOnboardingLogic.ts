import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import { MARKETING_ONBOARDING_STORAGE_KEYS } from './constants'
import type { marketingOnboardingLogicType } from './marketingOnboardingLogicType'

export type MarketingOnboardingStep = 'welcome' | 'add-source' | 'conversion-goals' | 'done'

const STEP_ORDER: MarketingOnboardingStep[] = ['welcome', 'add-source', 'conversion-goals', 'done']

export const marketingOnboardingLogic = kea<marketingOnboardingLogicType>([
    path(['scenes', 'marketing-analytics', 'Onboarding', 'marketingOnboardingLogic']),

    actions({
        setStep: (step: MarketingOnboardingStep) => ({ step }),
        goToNextStep: true,
        completeOnboarding: true,
        resetOnboarding: true,
        setShowOnboarding: (show: boolean) => ({ show }),
    }),

    reducers({
        currentStep: [
            (localStorage.getItem(MARKETING_ONBOARDING_STORAGE_KEYS.STEP) as MarketingOnboardingStep) || 'welcome',
            {
                setStep: (_, { step }) => step,
                goToNextStep: (state) => {
                    const currentIndex = STEP_ORDER.indexOf(state)
                    const nextIndex = Math.min(currentIndex + 1, STEP_ORDER.length - 1)
                    return STEP_ORDER[nextIndex]
                },
                resetOnboarding: () => 'welcome',
            },
        ],
        showOnboarding: [
            localStorage.getItem(MARKETING_ONBOARDING_STORAGE_KEYS.COMPLETED) !== 'true',
            {
                setShowOnboarding: (_, { show }) => show,
                completeOnboarding: () => false,
                resetOnboarding: () => true,
            },
        ],
    }),

    selectors({
        isLastStep: [(s) => [s.currentStep], (currentStep): boolean => currentStep === 'conversion-goals'],
    }),

    listeners(({ actions, values }) => ({
        setStep: ({ step }) => {
            localStorage.setItem(MARKETING_ONBOARDING_STORAGE_KEYS.STEP, step)
        },
        goToNextStep: () => {
            localStorage.setItem(MARKETING_ONBOARDING_STORAGE_KEYS.STEP, values.currentStep)
            if (values.currentStep === 'done') {
                actions.completeOnboarding()
            }
        },
        completeOnboarding: () => {
            localStorage.setItem(MARKETING_ONBOARDING_STORAGE_KEYS.COMPLETED, 'true')
            localStorage.removeItem(MARKETING_ONBOARDING_STORAGE_KEYS.STEP)
        },
        resetOnboarding: () => {
            localStorage.removeItem(MARKETING_ONBOARDING_STORAGE_KEYS.COMPLETED)
            localStorage.removeItem(MARKETING_ONBOARDING_STORAGE_KEYS.STEP)
        },
    })),
])
