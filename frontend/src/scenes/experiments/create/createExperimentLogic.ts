import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { ExperimentExposureCriteria, ExperimentMetric } from '~/queries/schema/schema-general'
import type { Experiment, FeatureFlagFilters, MultivariateFlagVariant } from '~/types'
import { ProductKey } from '~/types'

import { NEW_EXPERIMENT } from '../constants'
import { FORM_MODES, experimentLogic } from '../experimentLogic'
import { experimentSceneLogic } from '../experimentSceneLogic'
import { generateFeatureFlagKey } from './VariantsPanelCreateFeatureFlag'
import type { createExperimentLogicType } from './createExperimentLogicType'
import { variantsPanelLogic } from './variantsPanelLogic'
import { validateVariants } from './variantsPanelValidation'

const validateExperiment = (
    experiment: Experiment,
    featureFlagKeyValidation: { valid: boolean; error: string | null } | null,
    mode?: 'create' | 'link'
): boolean => {
    const validExperimentName = experiment.name !== null && experiment.name.trim().length > 0

    const variantsValidation = validateVariants({
        flagKey: experiment.feature_flag_key,
        variants: experiment.parameters.feature_flag_variants,
        featureFlagKeyValidation,
        mode,
    })

    return validExperimentName && !variantsValidation.hasErrors
}

/**
 * Fields that can be updated on an existing experiment.
 *
 * This list must match the backend's `expected_keys` in:
 * ee/clickhouse/views/experiments.py::ExperimentSerializer.update() (lines 373-392)
 *
 * The backend will reject any fields not in this list with a ValidationError.
 *
 * Note: 'deleted' is in backend but not in frontend types, so we omit it here.
 * Note: 'saved_metrics_ids' is handled separately in the payload but is also allowed.
 */
const ALLOWED_UPDATE_FIELDS: (keyof Experiment)[] = [
    'name',
    'description',
    'start_date',
    'end_date',
    'filters',
    'parameters',
    'archived',
    'secondary_metrics',
    'holdout',
    'exposure_criteria',
    'metrics',
    'metrics_secondary',
    'stats_config',
    'conclusion',
    'conclusion_comment',
    'primary_metrics_ordered_uuids',
    'secondary_metrics_ordered_uuids',
]

/**
 * Filters an experiment object to only include fields that can be updated.
 * This prevents validation errors from the backend when updating experiments.
 */
const filterExperimentForUpdate = (experiment: Experiment): Partial<Experiment> => {
    const filtered: any = {}

    for (const key of ALLOWED_UPDATE_FIELDS) {
        if (key in experiment) {
            filtered[key] = experiment[key as keyof Experiment]
        }
    }

    return filtered as Partial<Experiment>
}

export interface CreateExperimentLogicProps {
    experiment?: Experiment
    tabId?: string
}

export const createExperimentLogic = kea<createExperimentLogicType>([
    props({} as CreateExperimentLogicProps),
    key((props) => `${props.tabId ?? 'global'}-${props.experiment?.id ?? 'create-experiment'}`),
    path((key) => ['scenes', 'experiments', 'create', 'createExperimentLogic', key]),
    connect((props: CreateExperimentLogicProps) => {
        const experiment = props.experiment || { ...NEW_EXPERIMENT }
        const disabled = experiment.id !== 'new' && experiment.id !== null
        const variantsPanelLogicInstance = variantsPanelLogic({
            experiment,
            disabled,
        })

        return {
            values: [
                featureFlagLogic,
                ['featureFlags'],
                variantsPanelLogicInstance,
                ['featureFlagKeyDirty', 'featureFlagKeyValidation', 'featureFlagKeyValidationLoading'],
            ],
            actions: [
                eventUsageLogic,
                ['reportExperimentCreated', 'reportExperimentUpdated'],
                featureFlagsLogic,
                ['updateFlag'],
                teamLogic,
                ['addProductIntent'],
                variantsPanelLogicInstance,
                ['validateFeatureFlagKey'],
            ],
        }
    }),
    actions(() => ({
        setExperiment: (experiment: Experiment) => ({ experiment }),
        setExperimentValue: (name: string, value: any) => ({ name, value }),
        resetExperiment: true,
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
    reducers(({ props }) => ({
        experiment: [
            (props.experiment ?? { ...NEW_EXPERIMENT }) as Experiment & { feature_flag_filters?: FeatureFlagFilters },
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
                resetExperiment: () => props.experiment ?? { ...NEW_EXPERIMENT },
            },
        ],
        sharedMetrics: [
            (() => {
                if (!props.experiment?.saved_metrics) {
                    return { primary: [], secondary: [] }
                }

                const primary = props.experiment.saved_metrics
                    .filter((sm) => sm.metadata.type === 'primary')
                    .map((sm) => ({
                        ...sm.query,
                        name: sm.name,
                        sharedMetricId: sm.saved_metric,
                        isSharedMetric: true,
                    }))

                const secondary = props.experiment.saved_metrics
                    .filter((sm) => sm.metadata.type === 'secondary')
                    .map((sm) => ({
                        ...sm.query,
                        name: sm.name,
                        sharedMetricId: sm.saved_metric,
                        isSharedMetric: true,
                    }))

                return { primary, secondary }
            })() as { primary: ExperimentMetric[]; secondary: ExperimentMetric[] },
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
    })),
    selectors(() => ({
        canSubmitExperiment: [
            (s) => [s.experiment, s.featureFlagKeyValidation, s.mode],
            (
                experiment: Experiment,
                featureFlagKeyValidation: { valid: boolean; error: string | null } | null,
                mode: 'create' | 'link'
            ) => validateExperiment(experiment, featureFlagKeyValidation, mode),
        ],
        isEditMode: [
            (s) => [s.experiment],
            (experiment: Experiment) => experiment.id !== 'new' && experiment.id !== null,
        ],
        isCreateMode: [(s) => [s.isEditMode], (isEditMode: boolean) => !isEditMode],
        mode: [
            (s) => [s.experiment, (_, props) => props],
            (experiment: Experiment, props: CreateExperimentLogicProps): 'create' | 'link' => {
                const disabled = experiment.id !== 'new' && experiment.id !== null
                return variantsPanelLogic({ experiment: props.experiment || { ...NEW_EXPERIMENT }, disabled }).values
                    .mode
            },
        ],
    })),
    listeners(({ values, actions, props }) => ({
        setExperiment: () => {},
        setExperimentValue: ({ name, value }) => {
            // Only auto-generate flag key in create mode, not when editing
            if (name === 'name' && !values.featureFlagKeyDirty && values.isCreateMode) {
                const key = generateFeatureFlagKey(value)
                actions.setFeatureFlagConfig({
                    feature_flag_key: key,
                })
                actions.validateFeatureFlagKey(key)
            }
        },
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
                    variants: values.experiment.parameters.feature_flag_variants,
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

            try {
                const isEditMode = values.isEditMode

                // Make experiment eligible for timeseries
                const statsConfig = {
                    ...values.experiment?.stats_config,
                    ...(values.featureFlags[FEATURE_FLAGS.EXPERIMENT_TIMESERIES] && { timeseries: true }),
                    ...(values.featureFlags[FEATURE_FLAGS.EXPERIMENTS_USE_NEW_QUERY_BUILDER] && {
                        use_new_query_builder: true,
                    }),
                }

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

                const experimentPayload: Experiment = {
                    ...values.experiment,
                    stats_config: statsConfig,
                    saved_metrics_ids: savedMetrics,
                }

                let response: Experiment

                if (isEditMode) {
                    // Update existing experiment - filter to only allowed fields
                    const filteredPayload = {
                        ...filterExperimentForUpdate(experimentPayload),
                        // Ensure these are always included for update
                        stats_config: statsConfig,
                        saved_metrics_ids: savedMetrics,
                    }
                    response = (await api.update(
                        `api/projects/@current/experiments/${values.experiment.id}`,
                        filteredPayload
                    )) as Experiment
                } else {
                    // Create new experiment - send all fields
                    response = (await api.create(`api/projects/@current/experiments`, experimentPayload)) as Experiment
                }

                if (response.id) {
                    // Refresh tree navigation
                    refreshTreeItem('experiment', String(response.id))
                    if (response.feature_flag?.id) {
                        refreshTreeItem('feature_flag', String(response.feature_flag.id))
                    }

                    // Update our own state with the server response
                    // This ensures we have the full experiment data including feature_flag, etc.
                    actions.setExperiment(response)

                    if (isEditMode) {
                        // Update flow
                        actions.reportExperimentUpdated(response)
                        lemonToast.success('Experiment updated successfully!')
                    } else {
                        // Create flow
                        actions.reportExperimentCreated(response)
                        actions.addProductIntent({
                            product_type: ProductKey.EXPERIMENTS,
                            intent_context: ProductIntentContext.EXPERIMENT_CREATED,
                        })
                        actions.createExperimentSuccess()
                        lemonToast.success('Experiment created successfully!')
                        // Don't reset - we just set the fresh data above
                    }

                    actions.saveExperimentSuccess()

                    if (props.tabId) {
                        const sceneLogicInstance = experimentSceneLogic({ tabId: props.tabId })
                        sceneLogicInstance.actions.setSceneState(response.id, FORM_MODES.update)
                        const logicRef = sceneLogicInstance.values.experimentLogicRef

                        if (logicRef) {
                            logicRef.logic.actions.loadExperimentSuccess(response)
                        } else {
                            experimentLogic({ experimentId: response.id, tabId: props.tabId }).actions.loadExperimentSuccess(
                                response
                            )
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
