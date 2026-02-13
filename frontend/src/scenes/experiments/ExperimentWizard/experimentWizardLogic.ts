import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import type { Experiment, FeatureFlagType } from '~/types'

import { createExperimentLogic } from '../ExperimentForm/createExperimentLogic'
import type { experimentWizardLogicType } from './experimentWizardLogicType'

export type ExperimentWizardStep = 'about' | 'variants' | 'analytics'

const WIZARD_STEPS: ExperimentWizardStep[] = ['about', 'variants', 'analytics']

const STEP_ORDER: Record<ExperimentWizardStep, number> = {
    about: 0,
    variants: 1,
    analytics: 2,
}

export interface ExperimentWizardLogicProps {
    tabId: string
}

export const experimentWizardLogic = kea<experimentWizardLogicType>([
    path(['scenes', 'experiments', 'wizard', 'experimentWizardLogic']),

    props({} as ExperimentWizardLogicProps),

    key((props) => props.tabId),

    connect((props: ExperimentWizardLogicProps) => ({
        values: [
            createExperimentLogic({ tabId: props.tabId }),
            ['experiment', 'sharedMetrics', 'isExperimentSubmitting'],
        ],
        actions: [
            createExperimentLogic({ tabId: props.tabId }),
            [
                'setExperiment',
                'setExperimentValue',
                'setFeatureFlagConfig',
                'setExposureCriteria',
                'setSharedMetrics',
                'saveExperiment',
            ],
        ],
    })),

    actions({
        setStep: (step: ExperimentWizardStep) => ({ step }),
        nextStep: true,
        prevStep: true,
        resetWizard: true,
        openFullEditor: true,
        setLinkedFeatureFlag: (flag: FeatureFlagType | null) => ({ flag }),
    }),

    reducers(() => ({
        currentStep: [
            'about' as ExperimentWizardStep,
            {
                setStep: (_, { step }) => step,
                nextStep: (state) => {
                    const currentIndex = WIZARD_STEPS.indexOf(state)
                    return WIZARD_STEPS[Math.min(currentIndex + 1, WIZARD_STEPS.length - 1)]
                },
                prevStep: (state) => {
                    const currentIndex = WIZARD_STEPS.indexOf(state)
                    return WIZARD_STEPS[Math.max(currentIndex - 1, 0)]
                },
                resetWizard: () => 'about',
            },
        ],
        linkedFeatureFlag: [
            null as FeatureFlagType | null,
            {
                setLinkedFeatureFlag: (_, { flag }) => flag,
                resetWizard: () => null,
            },
        ],
    })),

    selectors({
        stepNumber: [(s) => [s.currentStep], (currentStep: ExperimentWizardStep): number => STEP_ORDER[currentStep]],
        isLastStep: [
            (s) => [s.currentStep],
            (currentStep: ExperimentWizardStep): boolean => currentStep === WIZARD_STEPS[WIZARD_STEPS.length - 1],
        ],
        isFirstStep: [
            (s) => [s.currentStep],
            (currentStep: ExperimentWizardStep): boolean => currentStep === WIZARD_STEPS[0],
        ],
        stepValidationErrors: [
            (s) => [s.experiment],
            (experiment: Experiment): Record<ExperimentWizardStep, string[]> => {
                const errors: Record<ExperimentWizardStep, string[]> = {
                    about: [],
                    variants: [],
                    analytics: [],
                }

                if (!experiment.name?.trim()) {
                    errors.about.push('Name is required')
                }

                if (!experiment.feature_flag_key?.trim()) {
                    errors.about.push('Feature flag key is required')
                }

                const variants = experiment.parameters?.feature_flag_variants ?? []
                if (variants.length < 2) {
                    errors.variants.push('At least two variants are required')
                }

                const totalRollout = variants.reduce((sum, v) => sum + (v.rollout_percentage ?? 0), 0)
                if (variants.length >= 2 && totalRollout !== 100) {
                    errors.variants.push('Variant percentages must sum to 100%')
                }

                return errors
            },
        ],
        currentStepHasErrors: [
            (s) => [s.stepValidationErrors, s.currentStep],
            (errors: Record<ExperimentWizardStep, string[]>, currentStep: ExperimentWizardStep): boolean => {
                return errors[currentStep]?.length > 0
            },
        ],
    }),

    listeners(() => ({
        openFullEditor: () => {
            router.actions.push(urls.experiment('new'))
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.resetWizard()
        },
    })),
])
