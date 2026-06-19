import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import { ProductKey } from '~/queries/schema/schema-general'

import { recommendProducts } from './data/recommendations'
import type { onboardingLogicType } from './onboardingLogicType'

export type OnboardingTrack = 'installer' | 'user'

export type OnboardingStepKey = 'create_org' | 'company' | 'install' | 'configure' | 'learn' | 'done'

const INSTALLER_STEPS: OnboardingStepKey[] = ['create_org', 'company', 'install', 'configure', 'done']
const USER_STEPS: OnboardingStepKey[] = ['create_org', 'company', 'learn', 'done']

export const onboardingLogic = kea<onboardingLogicType>([
    path(['scenes', 'onboarding', 'redesign', 'onboardingLogic']),
    actions({
        setTrack: (track: OnboardingTrack) => ({ track }),
        nextStep: true,
        previousStep: true,
        goToStep: (index: number) => ({ index }),
        setCurrentStepIndex: (index: number) => ({ index }),
        setName: (name: string) => ({ name }),
        setOrganizationName: (organizationName: string) => ({ organizationName }),
        setArchetype: (archetypeId: string | null) => ({ archetypeId }),
        setRole: (roleId: string | null) => ({ roleId }),
        setSelectedProducts: (products: ProductKey[]) => ({ products }),
        toggleProduct: (product: ProductKey) => ({ product }),
    }),
    reducers({
        track: ['installer' as OnboardingTrack, { setTrack: (_, { track }) => track }],
        currentStepIndex: [0, { setCurrentStepIndex: (_, { index }) => index }],
        name: ['', { setName: (_, { name }) => name }],
        organizationName: ['', { setOrganizationName: (_, { organizationName }) => organizationName }],
        archetypeId: [null as string | null, { setArchetype: (_, { archetypeId }) => archetypeId }],
        roleId: [null as string | null, { setRole: (_, { roleId }) => roleId }],
        selectedProducts: [
            [] as ProductKey[],
            {
                setSelectedProducts: (_, { products }) => products,
                toggleProduct: (state, { product }) =>
                    state.includes(product) ? state.filter((p) => p !== product) : [...state, product],
            },
        ],
    }),
    selectors({
        steps: [
            (s) => [s.track],
            (track): OnboardingStepKey[] => (track === 'installer' ? INSTALLER_STEPS : USER_STEPS),
        ],
        totalSteps: [(s) => [s.steps], (steps): number => steps.length],
        currentStepKey: [
            (s) => [s.steps, s.currentStepIndex],
            (steps, currentStepIndex): OnboardingStepKey =>
                steps[Math.min(currentStepIndex, steps.length - 1)] ?? 'create_org',
        ],
        isFirstStep: [(s) => [s.currentStepIndex], (currentStepIndex): boolean => currentStepIndex <= 0],
        isLastStep: [
            (s) => [s.steps, s.currentStepIndex],
            (steps, currentStepIndex): boolean => currentStepIndex >= steps.length - 1,
        ],
        recommendedProducts: [
            (s) => [s.archetypeId, s.roleId],
            (archetypeId, roleId): ProductKey[] => recommendProducts(archetypeId, roleId),
        ],
    }),
    listeners(({ actions, values }) => {
        const clamp = (index: number): number => Math.min(Math.max(index, 0), values.steps.length - 1)
        // Keep the selected products in sync with what the chosen archetype + role recommend. There is no manual
        // product step in the core flow yet, so re-seeding on each change is the desired behavior.
        const seedRecommended = (): void => actions.setSelectedProducts(values.recommendedProducts)
        return {
            nextStep: () => actions.setCurrentStepIndex(clamp(values.currentStepIndex + 1)),
            previousStep: () => actions.setCurrentStepIndex(clamp(values.currentStepIndex - 1)),
            goToStep: ({ index }) => actions.setCurrentStepIndex(clamp(index)),
            setArchetype: seedRecommended,
            setRole: seedRecommended,
        }
    }),
])
