import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import type { Experiment, FeatureFlagType } from '~/types'

import { createExperimentLogic } from '../ExperimentForm/createExperimentLogic'
import { variantsPanelLogic } from '../ExperimentForm/variantsPanelLogic'
import { NEW_EXPERIMENT } from '../constants'
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
            [
                'experiment',
                'sharedMetrics',
                'isExperimentSubmitting',
                'featureFlagKeyValidation',
                'featureFlagKeyValidationLoading',
            ],
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
            variantsPanelLogic({ experiment: { ...NEW_EXPERIMENT }, disabled: false }),
            ['validateFeatureFlagKey', 'clearFeatureFlagKeyValidation'],
        ],
    })),

    actions({
        // Public navigation actions — handled in listeners so we can
        // capture the departing step before changing it.
        setStep: (step: ExperimentWizardStep) => ({ step }),
        nextStep: true,
        prevStep: true,
        // Internal: applies the step change after departure logic runs.
        _applyStep: (step: ExperimentWizardStep) => ({ step }),
        markStepDeparted: (step: ExperimentWizardStep) => ({ step }),
        resetWizard: true,
        openFullEditor: true,
        toggleGuide: true,
        setLinkedFeatureFlag: (flag: FeatureFlagType | null) => ({ flag }),
    }),

    reducers(() => ({
        showGuide: [
            true,
            {
                toggleGuide: (state) => !state,
            },
        ],
        currentStep: [
            'about' as ExperimentWizardStep,
            {
                _applyStep: (_, { step }) => step,
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
        departedSteps: [
            {} as Record<string, boolean>,
            {
                markStepDeparted: (state, { step }) => ({ ...state, [step]: true }),
                resetWizard: () => ({}),
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
            (s) => [s.experiment, s.featureFlagKeyValidation, s.linkedFeatureFlag, s.departedSteps],
            (
                experiment: Experiment,
                featureFlagKeyValidation: { valid: boolean; error: string | null } | null,
                linkedFeatureFlag: FeatureFlagType | null,
                departedSteps: Record<string, boolean>
            ): Record<ExperimentWizardStep, string[]> => {
                const errors: Record<ExperimentWizardStep, string[]> = {
                    about: [],
                    variants: [],
                    analytics: [],
                }

                // Required field errors — only shown after the user has navigated
                // away from the step, so the form isn't red on first load.
                if (departedSteps.about) {
                    if (!experiment.name?.trim()) {
                        errors.about.push('Name is required')
                    }
                    if (!experiment.feature_flag_key?.trim()) {
                        errors.about.push('Feature flag key is required')
                    }
                }

                // Active validation errors — always shown once triggered
                if (!linkedFeatureFlag && featureFlagKeyValidation?.valid === false && featureFlagKeyValidation.error) {
                    errors.about.push(featureFlagKeyValidation.error)
                }

                const variants = experiment.parameters?.feature_flag_variants ?? []
                const variantKeys = variants.map((v) => v.key)
                const hasDuplicateKeys = variantKeys.length !== new Set(variantKeys).size
                const hasEmptyKeys = variants.some((v) => !v.key || v.key.trim().length === 0)

                if (hasEmptyKeys) {
                    errors.variants.push('All variants must have a key')
                }
                if (hasDuplicateKeys) {
                    errors.variants.push('Variant keys must be unique')
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

    listeners(({ actions, values }) => ({
        openFullEditor: () => {
            router.actions.push(urls.experiment('new'))
        },
        nextStep: () => {
            actions.markStepDeparted(values.currentStep)
            const currentIndex = WIZARD_STEPS.indexOf(values.currentStep)
            actions._applyStep(WIZARD_STEPS[Math.min(currentIndex + 1, WIZARD_STEPS.length - 1)])

            const key = values.experiment?.feature_flag_key
            if (key && !values.linkedFeatureFlag && values.featureFlagKeyValidation === null) {
                actions.validateFeatureFlagKey(key)
            }
        },
        prevStep: () => {
            actions.markStepDeparted(values.currentStep)
            const currentIndex = WIZARD_STEPS.indexOf(values.currentStep)
            actions._applyStep(WIZARD_STEPS[Math.max(currentIndex - 1, 0)])
        },
        setStep: ({ step }) => {
            actions.markStepDeparted(values.currentStep)
            actions._applyStep(step)

            const key = values.experiment?.feature_flag_key
            if (key && !values.linkedFeatureFlag && values.featureFlagKeyValidation === null) {
                actions.validateFeatureFlagKey(key)
            }
        },
        saveExperiment: () => {
            for (const step of WIZARD_STEPS) {
                actions.markStepDeparted(step)
            }
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.resetWizard()
        },
    })),
])
