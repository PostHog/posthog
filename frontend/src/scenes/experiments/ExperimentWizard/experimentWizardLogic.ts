import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import {
    ExperimentExposureCriteria,
    ExperimentMetric,
    ProductIntentContext,
    ProductKey,
} from '~/queries/schema/schema-general'
import type { Experiment, MultivariateFlagVariant } from '~/types'

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
    id: string
}

export const experimentWizardLogic = kea<experimentWizardLogicType>([
    path(['scenes', 'experiments', 'wizard', 'experimentWizardLogic']),

    props({} as ExperimentWizardLogicProps),

    key((props) => props.id),

    connect({
        actions: [eventUsageLogic, ['reportExperimentCreated'], teamLogic, ['addProductIntent']],
    }),

    actions({
        setStep: (step: ExperimentWizardStep) => ({ step }),
        nextStep: true,
        prevStep: true,
        resetWizard: true,

        setExperimentValue: (name: string, value: any) => ({ name, value }),
        setExperiment: (experiment: Experiment) => ({ experiment }),
        setFeatureFlagConfig: (config: {
            feature_flag_key?: string
            feature_flag_variants?: MultivariateFlagVariant[]
            parameters?: {
                feature_flag_variants?: MultivariateFlagVariant[]
                ensure_experience_continuity?: boolean
            }
        }) => ({ config }),
        setExposureCriteria: (criteria: ExperimentExposureCriteria) => ({ criteria }),
        setSharedMetrics: (sharedMetrics: { primary: ExperimentMetric[]; secondary: ExperimentMetric[] }) => ({
            sharedMetrics,
        }),

        saveExperiment: true,
        saveExperimentStarted: true,
        saveExperimentSuccess: (experiment: Experiment) => ({ experiment }),
        saveExperimentFailure: (error: string) => ({ error }),
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
        experiment: [
            { ...NEW_EXPERIMENT } as Experiment,
            {
                setExperiment: (_, { experiment }) => experiment,
                setExperimentValue: (state, { name, value }) => ({ ...state, [name]: value }),
                setExposureCriteria: (state, { criteria }) => ({
                    ...state,
                    exposure_criteria: {
                        ...state.exposure_criteria,
                        ...criteria,
                    },
                }),
                setFeatureFlagConfig: (state, { config }) => ({
                    ...state,
                    ...(config.feature_flag_key !== undefined && {
                        feature_flag_key: config.feature_flag_key,
                    }),
                    parameters: {
                        ...state.parameters,
                        ...(config.feature_flag_variants !== undefined && {
                            feature_flag_variants: config.feature_flag_variants,
                        }),
                        ...(config.parameters && config.parameters),
                    },
                }),
                resetWizard: () => ({ ...NEW_EXPERIMENT }),
            },
        ],
        sharedMetrics: [
            { primary: [], secondary: [] } as { primary: ExperimentMetric[]; secondary: ExperimentMetric[] },
            {
                setSharedMetrics: (_, { sharedMetrics }) => sharedMetrics,
                resetWizard: () => ({ primary: [], secondary: [] }),
            },
        ],
        isExperimentSubmitting: [
            false,
            {
                saveExperimentStarted: () => true,
                saveExperimentSuccess: () => false,
                saveExperimentFailure: () => false,
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

    listeners(({ actions, values }) => ({
        saveExperiment: async () => {
            if (values.isExperimentSubmitting) {
                return
            }

            actions.saveExperimentStarted()

            try {
                const schedulingConfig = {
                    ...values.experiment?.scheduling_config,
                    timeseries: true,
                }

                const savedMetrics = [
                    ...values.sharedMetrics.primary.map((metric) => ({
                        id: metric.sharedMetricId!,
                        metadata: { type: 'primary' as const },
                    })),
                    ...values.sharedMetrics.secondary.map((metric) => ({
                        id: metric.sharedMetricId!,
                        metadata: { type: 'secondary' as const },
                    })),
                ]

                const experimentPayload: Experiment = {
                    ...values.experiment,
                    scheduling_config: schedulingConfig,
                    saved_metrics_ids: savedMetrics,
                }

                const response = (await api.create(
                    'api/projects/@current/experiments',
                    experimentPayload
                )) as Experiment

                if (response.id) {
                    refreshTreeItem('experiment', String(response.id))
                    if (response.feature_flag?.id) {
                        refreshTreeItem('feature_flag', String(response.feature_flag.id))
                    }

                    actions.reportExperimentCreated(response)
                    actions.addProductIntent({
                        product_type: ProductKey.EXPERIMENTS,
                        intent_context: ProductIntentContext.EXPERIMENT_CREATED,
                    })
                    globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.CreateExperiment)

                    actions.saveExperimentSuccess(response)
                }
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to save experiment')
                actions.saveExperimentFailure(String(error))
            }
        },
        saveExperimentSuccess: ({ experiment }) => {
            lemonToast.success('Experiment created successfully!')
            router.actions.push(urls.experiment(experiment.id))
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.resetWizard()
        },
    })),
])
