import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils/objects'

import { experimentsConfigLogic } from '~/scenes/settings/environment/experimentsConfigLogic'
import { ConversionRateInputType, Experiment } from '~/types'

import { experimentsCalculateRunningTimeCreate } from 'products/experiments/frontend/generated/api'
import type {
    RunningTimeCalculationInputApi,
    RunningTimeCalculationResultApi,
} from 'products/experiments/frontend/generated/api.schemas'

import { experimentLogic } from '../experimentLogic'
import { experimentMetricsLogic } from '../experimentMetricsLogic'
import { isLaunched } from '../experimentsLogic'
import { modalsLogic } from '../modalsLogic'
import { getFlagVariants, getOrderedMetricsWithResults } from '../utils'
import {
    ManualCalculatorMetricType,
    baselineStatsFromResults,
    calculateCurrentExposures,
    calculateDaysElapsed,
    calculateExposureRate,
    getCalculatorMetricType,
} from './calculations'
import type { runningTimeLogicType } from './runningTimeLogicType'

export interface RunningTimeLogicProps {
    experiment: Experiment
}

export interface RunningTimeConfig {
    mode: 'automatic' | 'manual'
    mde: number
    metricType: ManualCalculatorMetricType
    baselineValue: number
    exposureRate: number
}

export interface ManualPreview {
    sampleSize: number | null
    runningTime: number | null
}

export const runningTimeLogic = kea<runningTimeLogicType>([
    path(['scenes', 'experiments', 'RunningTimeCalculator', 'runningTimeLogic']),
    props({} as RunningTimeLogicProps),
    key((props) => `${props.experiment.id}`),

    connect((props: RunningTimeLogicProps) => {
        const experimentId = props.experiment.id
        return {
            values: [
                experimentLogic({ experimentId }),
                ['experiment', 'orderedPrimaryMetricsWithResults', 'primaryMetricsResultsLoading', 'currentProjectId'],
                // On the recalculation flow, metric results live in experimentMetricsLogic, not experimentLogic.
                experimentMetricsLogic({ experiment: props.experiment }),
                [
                    'primaryMetricsResults as recalcPrimaryMetricsResults',
                    'primaryMetricsResultsErrors as recalcPrimaryMetricsResultsErrors',
                ],
                modalsLogic,
                ['isRunningTimeConfigModalOpen'],
                experimentsConfigLogic,
                ['defaultMinimumDetectableEffect'],
                featureFlagLogic,
                ['featureFlags'],
            ],
            actions: [
                experimentLogic({ experimentId }),
                ['setExperiment'],
                modalsLogic,
                ['closeRunningTimeConfigModal'],
            ],
        }
    }),

    actions({
        setConfig: (config: Partial<RunningTimeConfig>) => ({ config }),
        resetConfig: true,
        save: true,
        cancel: true,
        persistRunningTimeEstimate: true,
        setSaving: (saving: boolean) => ({ saving }),
    }),

    reducers({
        configOverrides: [
            null as Partial<RunningTimeConfig> | null,
            {
                setConfig: (state, { config }) => ({ ...state, ...config }),
                resetConfig: () => null,
            },
        ],
        isSaving: [
            false,
            {
                setSaving: (_, { saving }) => saving,
            },
        ],
    }),

    loaders(({ values }) => ({
        // Automatic mode: recommended sample size derived by the backend from live results baseline.
        automaticCalculation: [
            null as RunningTimeCalculationResultApi | null,
            {
                loadAutomaticCalculation: async (input: RunningTimeCalculationInputApi, breakpoint) => {
                    const result = await experimentsCalculateRunningTimeCreate(String(values.currentProjectId), input)
                    breakpoint()
                    return result
                },
            },
        ],
        // Manual mode: live preview of sample size / running time for the values being edited in the form.
        manualPreview: [
            { sampleSize: null, runningTime: null } as ManualPreview,
            {
                loadManualPreview: async (input: RunningTimeCalculationInputApi, breakpoint) => {
                    // Debounce burst typing in the form so we don't fire a request per keypress.
                    await breakpoint(300)
                    const result = await experimentsCalculateRunningTimeCreate(String(values.currentProjectId), input)
                    breakpoint()
                    return {
                        sampleSize: result.recommended_sample_size,
                        runningTime: result.recommended_running_time_days,
                    }
                },
            },
        ],
    })),

    selectors({
        numberOfVariants: [
            (s) => [s.experiment],
            (experiment): number => getFlagVariants(experiment?.feature_flag).length || 2,
        ],

        isManualMode: [
            (s) => [s.experiment],
            (experiment): boolean =>
                experiment?.running_time_calculation?.exposure_estimate_config?.conversionRateInputType ===
                ConversionRateInputType.MANUAL,
        ],

        initialConfig: [
            (s) => [s.experiment, s.isManualMode, s.defaultMinimumDetectableEffect],
            (experiment, isManualMode, defaultMinimumDetectableEffect): RunningTimeConfig => {
                // Pre-launch experiments must use manual mode (no data available for automatic)
                const isPreLaunch = !isLaunched(experiment)
                const exposureEstimateConfig = experiment?.running_time_calculation?.exposure_estimate_config
                return {
                    mode: isPreLaunch || isManualMode ? 'manual' : 'automatic',
                    mde:
                        experiment?.running_time_calculation?.minimum_detectable_effect ??
                        defaultMinimumDetectableEffect,
                    metricType: (exposureEstimateConfig?.manualMetricType as ManualCalculatorMetricType) ?? 'funnel',
                    baselineValue: exposureEstimateConfig?.manualBaselineValue ?? 5,
                    exposureRate: exposureEstimateConfig?.manualExposureRate ?? 100,
                }
            },
        ],

        config: [
            (s) => [s.initialConfig, s.configOverrides],
            (initialConfig, configOverrides): RunningTimeConfig =>
                configOverrides ? { ...initialConfig, ...configOverrides } : initialConfig,
        ],

        // Pulled out as primitives so automaticCalculationInput stays stable when the experiment object
        // is replaced (e.g. after persisting an estimate) but the underlying values are unchanged.
        mde: [(s) => [s.config], (config): number => config.mde],
        mode: [(s) => [s.config], (config): RunningTimeConfig['mode'] => config.mode],

        // Legacy flow exposes metric results via experimentLogic; the recalculation flow exposes them
        // via experimentMetricsLogic. Pick whichever is active so automatic mode always has a baseline.
        metricsWithResults: [
            (s) => [
                s.experiment,
                s.featureFlags,
                s.orderedPrimaryMetricsWithResults,
                s.recalcPrimaryMetricsResults,
                s.recalcPrimaryMetricsResultsErrors,
            ],
            (experiment, featureFlags, legacyMetricsWithResults, recalcResults, recalcErrors) => {
                if (experiment && featureFlags[FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION]) {
                    return getOrderedMetricsWithResults(experiment, recalcResults, recalcErrors, [], [], false)
                }
                return legacyMetricsWithResults
            },
        ],

        currentExposures: [
            (s) => [s.metricsWithResults],
            (results): number | null => calculateCurrentExposures(results?.[0]?.result ?? null),
        ],

        // Request body for the automatic-mode calculation, or null when not applicable (manual mode / no results yet).
        automaticCalculationInput: [
            (s) => [s.mode, s.metricsWithResults, s.numberOfVariants, s.mde],
            (mode, results, numberOfVariants, mde): RunningTimeCalculationInputApi | null => {
                // Gate on the in-form mode rather than the persisted mode. While the form is in manual mode
                // (even if the experiment is still saved as automatic), the automatic estimate is neither
                // shown nor persisted, so editing the MDE shouldn't fire a wasted automatic calculation.
                if (mode !== 'automatic') {
                    return null
                }
                const firstMetric = results?.[0]
                if (!firstMetric?.metric || !firstMetric?.result?.baseline) {
                    return null
                }
                return {
                    metric_type: getCalculatorMetricType(firstMetric.metric),
                    minimum_detectable_effect: mde,
                    number_of_variants: numberOfVariants,
                    baseline_stats: baselineStatsFromResults(firstMetric.result.baseline),
                }
            },
        ],

        // Request body for the live manual-mode preview, or null when the form inputs aren't usable yet.
        manualPreviewInput: [
            (s) => [s.config, s.numberOfVariants],
            (config, numberOfVariants): RunningTimeCalculationInputApi | null => {
                // Use !(x > 0) to catch NaN, 0, negative, and undefined
                if (config.mode !== 'manual' || !(config.baselineValue > 0) || !(config.mde > 0)) {
                    return null
                }
                const baselineValue = config.metricType === 'funnel' ? config.baselineValue / 100 : config.baselineValue
                return {
                    metric_type: config.metricType,
                    minimum_detectable_effect: config.mde,
                    number_of_variants: numberOfVariants,
                    baseline_value: baselineValue,
                    exposure_rate_per_day: config.exposureRate > 0 ? config.exposureRate : undefined,
                }
            },
        ],

        targetSampleSize: [
            (s) => [s.isManualMode, s.experiment, s.automaticCalculationInput, s.automaticCalculation],
            (isManualMode, experiment, automaticInput, automaticCalculation): number | null => {
                if (isManualMode) {
                    // Persisted by the save listener from the same backend calculation.
                    return experiment?.running_time_calculation?.recommended_sample_size ?? null
                }
                if (!automaticInput) {
                    return null
                }
                return automaticCalculation?.recommended_sample_size ?? null
            },
        ],

        dailyExposureRate: [
            (s) => [s.isManualMode, s.experiment, s.currentExposures],
            (isManualMode, experiment, currentExposures): number | null => {
                if (isManualMode) {
                    return experiment?.running_time_calculation?.exposure_estimate_config?.manualExposureRate ?? null
                }

                // Automatic mode: calculate from actual rate
                const daysElapsed = calculateDaysElapsed(experiment?.start_date ?? null)
                return calculateExposureRate(currentExposures, daysElapsed)
            },
        ],

        // Days until we reach target sample size
        remainingDays: [
            (s) => [s.targetSampleSize, s.currentExposures, s.dailyExposureRate, s.experiment],
            (target, current, rate, experiment): number | null => {
                if (!target || !rate || rate <= 0) {
                    return null
                }

                // Need minimum data for automatic mode
                const daysElapsed = calculateDaysElapsed(experiment?.start_date ?? null)
                if (!daysElapsed || daysElapsed < 1 || !current || current < 100) {
                    // Not enough data yet - show total estimated time if we have rate
                    if (rate > 0) {
                        return Math.ceil(target / rate)
                    }
                    return null
                }

                if (current >= target) {
                    return 0
                }

                const remaining = target - current
                return Math.ceil(remaining / rate)
            },
        ],
        isComplete: [
            (s) => [s.currentExposures, s.targetSampleSize],
            (current, target): boolean => current !== null && target !== null && current >= target,
        ],
        manualFormPreview: [
            (s) => [s.manualPreviewInput, s.manualPreview],
            (input, preview): ManualPreview => (input ? preview : { sampleSize: null, runningTime: null }),
        ],
    }),

    subscriptions(({ actions }) => ({
        // kea-subscriptions fires on reference change. The recalc poll replaces the metric-results array every
        // tick, so these inputs get a fresh object reference even when their values are identical, which would
        // re-fire the calculation POST on every poll. Skip the dispatch unless the value actually changed.
        automaticCalculationInput: (
            input: RunningTimeCalculationInputApi | null,
            oldInput: RunningTimeCalculationInputApi | null
        ) => {
            if (input && !objectsEqual(input, oldInput)) {
                actions.loadAutomaticCalculation(input)
            }
        },
        manualPreviewInput: (
            input: RunningTimeCalculationInputApi | null,
            oldInput: RunningTimeCalculationInputApi | null
        ) => {
            if (input && !objectsEqual(input, oldInput)) {
                actions.loadManualPreview(input)
            }
        },
    })),

    listeners(({ actions, values, props }) => ({
        // Persist the automatic estimate once the backend calculation lands and the selectors are fresh.
        loadAutomaticCalculationSuccess: () => {
            actions.persistRunningTimeEstimate()
        },

        persistRunningTimeEstimate: async () => {
            const { isManualMode, remainingDays, targetSampleSize, experiment, currentProjectId, configOverrides } =
                values

            // Skip while the user has unsaved edits — `save` owns persistence then. Auto-persisting a
            // transient value here (e.g. right after `resetConfig`) would race with the save and revert it.
            if (
                configOverrides ||
                isManualMode ||
                !isLaunched(experiment) ||
                remainingDays === null ||
                targetSampleSize === null
            ) {
                return
            }

            const savedRunningTime = experiment?.running_time_calculation?.recommended_running_time
            const savedSampleSize = experiment?.running_time_calculation?.recommended_sample_size
            if (savedRunningTime === remainingDays && savedSampleSize === targetSampleSize) {
                return
            }

            const updatedRunningTimeCalculation = {
                ...experiment?.running_time_calculation,
                recommended_running_time: remainingDays,
                recommended_sample_size: targetSampleSize,
            }

            await api.update(`api/projects/${currentProjectId}/experiments/${props.experiment.id}`, {
                running_time_calculation: updatedRunningTimeCalculation,
            })

            actions.setExperiment({ running_time_calculation: updatedRunningTimeCalculation })
        },

        save: async () => {
            const { config, numberOfVariants, experiment, currentProjectId } = values

            actions.setSaving(true)
            try {
                let update: Partial<Experiment> & { update_feature_flag_params?: boolean }
                if (config.mode === 'manual') {
                    // Convert NaN (from empty input) to 0
                    const manualBaselineValue = Number.isNaN(config.baselineValue) ? 0 : config.baselineValue
                    const manualExposureRate = Number.isNaN(config.exposureRate) ? 0 : config.exposureRate

                    const baselineValue =
                        config.metricType === 'funnel' ? manualBaselineValue / 100 : manualBaselineValue

                    let sampleSize: number | null = null
                    let runningTime: number | null = null
                    if (baselineValue > 0) {
                        const result = await experimentsCalculateRunningTimeCreate(String(currentProjectId), {
                            metric_type: config.metricType,
                            minimum_detectable_effect: config.mde,
                            number_of_variants: numberOfVariants,
                            baseline_value: baselineValue,
                            exposure_rate_per_day: manualExposureRate > 0 ? manualExposureRate : undefined,
                        })
                        sampleSize = result.recommended_sample_size
                        runningTime = result.recommended_running_time_days
                    }

                    update = {
                        running_time_calculation: {
                            ...experiment?.running_time_calculation,
                            minimum_detectable_effect: config.mde,
                            recommended_sample_size: sampleSize ?? undefined,
                            recommended_running_time: runningTime ?? undefined,
                            exposure_estimate_config: {
                                conversionRateInputType: ConversionRateInputType.MANUAL,
                                manualMetricType: config.metricType,
                                manualBaselineValue,
                                manualExposureRate,
                            },
                        },
                        update_feature_flag_params: false,
                    }
                } else {
                    update = {
                        running_time_calculation: {
                            ...experiment?.running_time_calculation,
                            minimum_detectable_effect: config.mde,
                            exposure_estimate_config: {
                                conversionRateInputType: ConversionRateInputType.AUTOMATIC,
                            },
                        },
                        update_feature_flag_params: false,
                    }
                }

                // Await so the experiment reflects the saved config before resetConfig below. Otherwise the
                // transient (overrides cleared, experiment not yet updated) would re-trigger the automatic
                // auto-persist with stale values and revert the save.
                await experimentLogic({ experimentId: props.experiment.id }).asyncActions.updateExperiment(update)
            } catch {
                // Keep the modal open (don't close/reset below) so the user can retry.
                lemonToast.error('Failed to save running time settings. Please try again.')
                return
            } finally {
                actions.setSaving(false)
            }
            actions.closeRunningTimeConfigModal()
            actions.resetConfig()
        },

        cancel: () => {
            actions.closeRunningTimeConfigModal()
            actions.resetConfig()
        },
    })),
])
