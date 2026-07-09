import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'
import { tryShowMCPHint } from 'lib/components/MCPHint/mcpHintLogic'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { isExperimentMetric } from '~/queries/schema-guards'
import {
    ExperimentExposureCriteria,
    ExperimentMetric,
    ProductIntentContext,
    ProductKey,
} from '~/queries/schema/schema-general'
import type { Experiment, FeatureFlagFilters, MultivariateFlagVariant } from '~/types'

import { NEW_EXPERIMENT } from '../constants'
import { FORM_MODES, experimentLogic } from '../experimentLogic'
import { experimentSceneLogic } from '../experimentSceneLogic'
import { toExperimentWritePayload } from '../utils'
import type { createExperimentLogicType } from './createExperimentLogicType'
import { validateExperimentSubmission } from './experimentSubmissionValidation'
import type { FeatureFlagKeyValidation } from './variantsPanelLogic'
import { variantsPanelLogic } from './variantsPanelLogic'
import { validateVariants } from './variantsPanelValidation'

const DRAFT_TTL_MS = 7 * 24 * 60 * 60 * 1000

// Scope the draft key per project so a draft started in one project can't prefill or be submitted in another within the same browser session.
export const DRAFT_STORAGE_KEY = `experiment-draft-${window.POSTHOG_APP_CONTEXT?.current_team?.id ?? 'unknown'}`

type ExperimentDraft = {
    experiment: Experiment
    timestamp: number
}

const readDraftFromStorage = (): Experiment | null => {
    if (typeof sessionStorage === 'undefined') {
        return null
    }
    const raw = sessionStorage.getItem(DRAFT_STORAGE_KEY)
    if (!raw) {
        return null
    }
    try {
        const parsed = JSON.parse(raw) as ExperimentDraft | Experiment
        if (parsed && typeof parsed === 'object' && 'experiment' in parsed && 'timestamp' in parsed) {
            const { experiment, timestamp } = parsed as ExperimentDraft
            if (Date.now() - timestamp > DRAFT_TTL_MS) {
                sessionStorage.removeItem(DRAFT_STORAGE_KEY)
                return null
            }
            return experiment
        }
        return parsed as Experiment
    } catch {
        return null
    }
}

const writeDraftToStorage = (experiment: Experiment): void => {
    if (typeof sessionStorage === 'undefined') {
        return
    }
    const draft: ExperimentDraft = { experiment, timestamp: Date.now() }
    sessionStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft))
}

const clearDraftStorage = (): void => {
    if (typeof sessionStorage === 'undefined') {
        return
    }
    sessionStorage.removeItem(DRAFT_STORAGE_KEY)
}

export interface CreateExperimentLogicProps {}

export const createExperimentLogic = kea<createExperimentLogicType>([
    props({} as CreateExperimentLogicProps),
    key(() => 'create-experiment'),
    path((key) => ['scenes', 'experiments', 'create', 'createExperimentLogic', key]),
    connect(() => ({
        values: [
            variantsPanelLogic({ experiment: { ...NEW_EXPERIMENT }, disabled: false }),
            ['featureFlagKeyValidation', 'featureFlagKeyValidationLoading'],
            projectLogic,
            ['currentProjectId'],
        ],
        actions: [
            eventUsageLogic,
            ['reportExperimentCreated'],
            featureFlagsLogic,
            ['updateFlag'],
            teamLogic,
            ['addProductIntent'],
        ],
    })),
    actions(() => ({
        setExperiment: (experiment: Experiment) => ({ experiment }),
        setExperimentValue: (name: string, value: any) => ({ name, value }),
        resetExperiment: true,
        cancelForm: true,
        setExposureCriteria: (criteria: ExperimentExposureCriteria) => ({ criteria }),
        setFeatureFlagConfig: (config: {
            feature_flag_key?: string
            feature_flag_variants?: MultivariateFlagVariant[]
            parameters?: {
                feature_flag_variants?: MultivariateFlagVariant[]
                ensure_experience_continuity?: boolean
            }
        }) => ({ config }),
        saveExperiment: true,
        saveExperimentStarted: true,
        saveExperimentSuccess: true,
        saveExperimentFailure: true,
        createExperimentSuccess: true,
        setExperimentErrors: (errors: Record<string, string>) => ({ errors }),
        validateField: (field: 'name') => ({ field }),
        setSharedMetrics: (sharedMetrics: { primary: ExperimentMetric[]; secondary: ExperimentMetric[] }) => ({
            sharedMetrics,
        }),
    })),
    reducers(() => ({
        experiment: [
            { ...NEW_EXPERIMENT } as Experiment & { feature_flag_filters?: FeatureFlagFilters },
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
                        // Handle both flat structure (feature_flag_variants) and nested (parameters.*)
                        ...(config.feature_flag_variants !== undefined && {
                            feature_flag_variants: config.feature_flag_variants,
                        }),
                        ...(config.parameters && config.parameters),
                    },
                }),
                updateFeatureFlagKey: (state, { key }) => ({ ...state, feature_flag_key: key }),
                resetExperiment: () => ({ ...NEW_EXPERIMENT }),
            },
        ],
        sharedMetrics: [
            { primary: [], secondary: [] } as { primary: ExperimentMetric[]; secondary: ExperimentMetric[] },
            {
                setSharedMetrics: (_, { sharedMetrics }) => sharedMetrics,
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
        experimentErrors: [
            {} as Record<string, string>,
            {
                setExperimentErrors: (_, { errors }) => errors,
                saveExperimentSuccess: () => ({}),
                createExperimentSuccess: () => ({}),
                resetExperiment: () => ({}),
            },
        ],
        formCanceled: [
            false,
            {
                cancelForm: () => true,
            },
        ],
    })),
    selectors(() => ({
        canSubmitExperiment: [
            (s) => [s.experiment, s.featureFlagKeyValidation, s.mode, s.experimentErrors],
            (
                experiment: Experiment,
                featureFlagKeyValidation: FeatureFlagKeyValidation | null,
                mode: 'create' | 'link',
                experimentErrors: Record<string, string>
            ) => {
                const validation = validateExperimentSubmission({
                    experiment,
                    featureFlagKeyValidation,
                    mode,
                    experimentErrors,
                })
                return validation.isValid
            },
        ],
        experimentValidationErrors: [
            (s) => [s.experiment, s.featureFlagKeyValidation, s.mode, s.experimentErrors],
            (
                experiment: Experiment,
                featureFlagKeyValidation: FeatureFlagKeyValidation | null,
                mode: 'create' | 'link',
                experimentErrors: Record<string, string>
            ): string | undefined => {
                const validation = validateExperimentSubmission({
                    experiment,
                    featureFlagKeyValidation,
                    mode,
                    experimentErrors,
                })
                return validation.errors.length > 0 ? validation.errors.join(', ') : undefined
            },
        ],
        mode: [
            (s) => [s.experiment],
            (): 'create' | 'link' => {
                return variantsPanelLogic({ experiment: { ...NEW_EXPERIMENT }, disabled: false }).values.mode
            },
        ],
    })),
    events(({ actions, values }) => ({
        afterMount: () => {
            if (values.experiment.id !== 'new') {
                return
            }

            try {
                const { searchParams } = router.values.currentLocation
                const { metric, name } = searchParams

                const parsedMetric = typeof metric === 'string' ? JSON.parse(metric) : metric

                if (name && isExperimentMetric(parsedMetric)) {
                    actions.setExperiment({
                        ...NEW_EXPERIMENT,
                        metrics: parsedMetric ? [parsedMetric] : [],
                        name: name ?? '',
                    })

                    lemonToast.success('Metric added successfully!')

                    return
                }
            } catch (error) {
                console.error('Error parsing metric from URL', error)
                lemonToast.error('Error parsing metric from URL')
                // Continue to draft fallback
            }

            const draft = readDraftFromStorage()
            if (draft) {
                actions.setExperiment(draft)
            }
        },
        beforeUnmount: () => {
            if (values.formCanceled || values.experiment.id !== 'new') {
                return
            }
            // Use cases covered:
            // - navigating away from the form without saving
            writeDraftToStorage(values.experiment)
        },
    })),
    listeners(({ values, actions }) => ({
        cancelForm: () => {
            if (values.experiment.id !== 'new') {
                return
            }
            clearDraftStorage()
        },
        setExperiment: () => {},
        setExperimentValue: () => {},
        validateField: ({ field }) => {
            if (field === 'name') {
                const name = values.experiment.name
                if (!name || name.trim().length === 0) {
                    actions.setExperimentErrors({ name: 'Name is required' })
                } else {
                    actions.setExperimentErrors({})
                }
            }
        },
        saveExperiment: async () => {
            // Prevent double submission
            if (values.isExperimentSubmitting) {
                return
            }

            // Check if async validation is still loading
            if (values.featureFlagKeyValidationLoading) {
                lemonToast.error('Please wait for validation to complete')
                actions.saveExperimentFailure()
                return
            }

            // Clear previous errors before validation is triggered
            actions.setExperimentErrors({})

            // Validate using canSubmitExperiment
            if (!values.canSubmitExperiment) {
                // Set field errors
                const errors: Record<string, string> = {}
                if (!values.experiment.name?.trim()) {
                    errors.name = 'Name is required'
                }
                actions.setExperimentErrors(errors)

                // Show toast with what's wrong
                const validation = validateVariants({
                    flagKey: values.experiment.feature_flag_key,
                    variants: values.experiment.parameters?.feature_flag_variants ?? [],
                    featureFlagKeyValidation: values.featureFlagKeyValidation,
                    mode: values.mode,
                })
                if (validation.hasErrors) {
                    lemonToast.error('Please fix variants configuration')
                } else {
                    lemonToast.error('Experiment is not valid')
                }

                actions.saveExperimentFailure()
                return
            }

            // Set loading state after all validation passes
            actions.saveExperimentStarted()

            // Whether the key is available decides whether flag config is sent (an available key
            // means the backend creates the flag and applies the config; an existing key means the
            // experiment links to that flag as-is and explicit config is rejected). A missing or
            // stale availability check must not decide this silently: re-run it, and fail loud if
            // it still can't complete.
            const flagKey = values.experiment.feature_flag_key
            const panelLogic = variantsPanelLogic({ experiment: { ...NEW_EXPERIMENT }, disabled: false })
            if (values.featureFlagKeyValidation?.key !== flagKey) {
                try {
                    await panelLogic.asyncActions.validateFeatureFlagKey(flagKey)
                } catch {
                    // Handled below: featureFlagKeyValidation stays stale or null.
                }
            }
            const keyValidation = panelLogic.values.featureFlagKeyValidation
            if (keyValidation?.key !== flagKey) {
                lemonToast.error("Couldn't verify the feature flag key. Please try again.")
                actions.saveExperimentFailure()
                return
            }

            try {
                const savedMetrics = [
                    ...values.sharedMetrics.primary.map((metric) => ({
                        id: metric.sharedMetricId!,
                        metadata: {
                            type: 'primary' as const,
                        },
                    })),
                    ...values.sharedMetrics.secondary.map((metric) => ({
                        id: metric.sharedMetricId!,
                        metadata: {
                            type: 'secondary' as const,
                        },
                    })),
                ]

                // A key confirmed available means the backend will create the flag and can apply
                // config to it; a taken key means the experiment links to the pre-existing flag
                // as-is, and the API rejects explicit flag config.
                const experimentPayload = {
                    ...toExperimentWritePayload(values.experiment, {
                        omitFlagConfig: keyValidation.valid !== true,
                    }),
                    saved_metrics_ids: savedMetrics,
                }

                const response = (await api.create(
                    `api/projects/${values.currentProjectId}/experiments`,
                    experimentPayload
                )) as Experiment

                if (response.id) {
                    // Refresh tree navigation
                    refreshTreeItem('experiment', String(response.id))
                    if (response.feature_flag?.id) {
                        refreshTreeItem('feature_flag', String(response.feature_flag.id))
                    }

                    // Update our own state with the server response
                    // This ensures we have the full experiment data including feature_flag, etc.
                    actions.setExperiment(response)

                    actions.addProductIntent({
                        product_type: ProductKey.EXPERIMENTS,
                        intent_context: ProductIntentContext.EXPERIMENT_CREATED,
                    })
                    actions.createExperimentSuccess()
                    globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.CreateExperiment)
                    lemonToast.success('Experiment created successfully!')
                    tryShowMCPHint('experiments.create', {
                        derivedPrompt: response.name ? `Create an A/B experiment called ${response.name}` : undefined,
                    })
                    // Don't reset - we just set the fresh data above

                    actions.saveExperimentSuccess()
                    clearDraftStorage()

                    const sceneLogicInstance = experimentSceneLogic.findMounted()
                    if (sceneLogicInstance) {
                        sceneLogicInstance.actions.setSceneState(response.id, FORM_MODES.update)
                        const logicRef = sceneLogicInstance.values.experimentLogicRef

                        if (logicRef) {
                            logicRef.logic.actions.loadExperimentSuccess(response)
                        } else {
                            experimentLogic({
                                experimentId: response.id,
                            }).actions.loadExperimentSuccess(response)
                        }
                    } else {
                        const viewLogic = experimentLogic({ experimentId: response.id })
                        viewLogic.actions.loadExperimentSuccess(response)
                        router.actions.push(urls.experiment(response.id))
                    }
                }
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to save experiment')
                actions.saveExperimentFailure()
            }
        },
    })),
])
