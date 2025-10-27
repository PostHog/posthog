import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
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
import { generateFeatureFlagKey } from './VariantsPanelCreateFeatureFlag'
import type { createExperimentLogicType } from './createExperimentLogicType'
import { variantsPanelLogic } from './variantsPanelLogic'
import { validateVariants } from './variantsPanelValidation'

const validateExperiment = (
    experiment: Experiment,
    featureFlagKeyValidation: { valid: boolean; error: string | null } | null
): boolean => {
    const validExperimentName = experiment.name !== null && experiment.name.trim().length > 0

    const variantsValidation = validateVariants({
        flagKey: experiment.feature_flag_key,
        variants: experiment.parameters.feature_flag_variants,
        featureFlagKeyValidation,
    })

    return validExperimentName && !variantsValidation.hasErrors
}

/**
 * TODO: we need to give new/linked feature flag the same treatment as shared metrics.
 * feature flag context? like metrics context?
 */
export type CreateExperimentLogicProps = Partial<{
    experiment: Experiment
}>

export const createExperimentLogic = kea<createExperimentLogicType>([
    props({} as CreateExperimentLogicProps),
    key((props) => props.experiment?.id || 'create-experiment'),
    path((key) => ['scenes', 'experiments', 'create', 'createExperimentLogic', key]),
    connect(() => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            variantsPanelLogic,
            ['featureFlagKeyDirty', 'featureFlagKeyValidation'],
        ],
        actions: [
            eventUsageLogic,
            ['reportExperimentCreated', 'reportExperimentUpdated'],
            featureFlagsLogic,
            ['updateFlag'],
            teamLogic,
            ['addProductIntent'],
            variantsPanelLogic,
            ['validateFeatureFlagKey'],
        ],
    })),
    forms(({ actions, props }) => ({
        experiment: {
            options: { showErrorsOnTouch: true },
            defaults: (props.experiment ?? { ...NEW_EXPERIMENT }) as Experiment,
            errors: ({ name }: Experiment) => ({
                name: !name ? 'Name is required' : undefined,
            }),
            submit: () => {
                actions.createExperiment()
            },
        },
    })),
    actions(() => ({
        setExperiment: (experiment: Experiment) => ({ experiment }),
        setExposureCriteria: (criteria: ExperimentExposureCriteria) => ({ criteria }),
        setFeatureFlagConfig: (config: {
            feature_flag_key?: string
            feature_flag_variants?: MultivariateFlagVariant[]
            parameters?: {
                feature_flag_variants?: MultivariateFlagVariant[]
                ensure_experience_continuity?: boolean
            }
        }) => ({ config }),
        createExperiment: () => ({}),
        createExperimentSuccess: true,
        setSharedMetrics: (sharedMetrics: { primary: ExperimentMetric[]; secondary: ExperimentMetric[] }) => ({
            sharedMetrics,
        }),
    })),
    reducers(({ props }) => ({
        experiment: [
            (props.experiment ?? { ...NEW_EXPERIMENT }) as Experiment & { feature_flag_filters?: FeatureFlagFilters },
            {
                setExperiment: (_, { experiment }) => experiment,
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
    })),
    selectors(() => ({
        canSubmitExperiment: [
            (s) => [s.experiment, s.featureFlagKeyValidation],
            (experiment: Experiment, featureFlagKeyValidation: { valid: boolean; error: string | null } | null) =>
                validateExperiment(experiment, featureFlagKeyValidation),
        ],
        isEditMode: [
            (s) => [s.experiment],
            (experiment: Experiment) => experiment.id !== 'new' && experiment.id !== null,
        ],
        isCreateMode: [(s) => [s.isEditMode], (isEditMode: boolean) => !isEditMode],
    })),
    listeners(({ values, actions }) => ({
        setExperiment: () => {},
        setExperimentValue: ({ name, value }) => {
            if (name === 'name' && !values.featureFlagKeyDirty) {
                const key = generateFeatureFlagKey(value)
                actions.setFeatureFlagConfig({
                    feature_flag_key: key,
                })
                actions.validateFeatureFlagKey(key)
            }
        },
        createExperiment: async () => {
            if (!values.canSubmitExperiment) {
                lemonToast.error('Experiment is not valid')
                return
            }

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
                // Update existing experiment
                response = (await api.update(
                    `api/projects/@current/experiments/${values.experiment.id}`,
                    experimentPayload
                )) as Experiment
            } else {
                // Create new experiment
                response = (await api.create(`api/projects/@current/experiments`, experimentPayload)) as Experiment
            }

            if (response.id) {
                // Refresh tree navigation
                refreshTreeItem('experiment', String(response.id))
                if (response.feature_flag?.id) {
                    refreshTreeItem('feature_flag', String(response.feature_flag.id))
                }

                if (isEditMode) {
                    // Update flow
                    // Report analytics
                    actions.reportExperimentUpdated(response)
                    // Show success toast
                    lemonToast.success('Experiment updated successfully!')
                } else {
                    // Create flow
                    // Report analytics
                    actions.reportExperimentCreated(response)
                    // Add product intent
                    actions.addProductIntent({
                        product_type: ProductKey.EXPERIMENTS,
                        intent_context: ProductIntentContext.EXPERIMENT_CREATED,
                    })

                    // Show success toast with view button
                    lemonToast.success('Experiment created successfully!')

                    // Reset form for next experiment (clear persisted state)
                    actions.resetExperiment()
                }

                // Navigate to experiment page
                router.actions.push(urls.experiment(response.id))
            }
        },
    })),
])
