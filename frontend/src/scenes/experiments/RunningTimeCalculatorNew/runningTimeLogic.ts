import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'

import { ConversionRateInputType, Experiment } from '~/types'

import { DEFAULT_MDE, experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import {
    ManualCalculatorMetricType,
    calculateBaselineValue,
    calculateCurrentExposures,
    calculateDaysElapsed,
    calculateExposureRate,
    calculateRecommendedSampleSize,
    calculateSampleSize,
} from './calculations'
import type { runningTimeLogicType } from './runningTimeLogicType'

export interface RunningTimeLogicProps {
    experimentId: Experiment['id']
    tabId: string
}

export interface RunningTimeConfig {
    mode: 'automatic' | 'manual'
    mde: number
    metricType: ManualCalculatorMetricType
    baselineValue: number
    exposureRate: number
}

export const runningTimeLogic = kea<runningTimeLogicType>([
    path(['scenes', 'experiments', 'RunningTimeCalculatorNew', 'runningTimeLogic']),
    props({} as RunningTimeLogicProps),
    key((props) => `${props.experimentId}-${props.tabId}`),

    connect((props: RunningTimeLogicProps) => ({
        values: [
            experimentLogic({ experimentId: props.experimentId, tabId: props.tabId }),
            ['experiment', 'orderedPrimaryMetricsWithResults', 'primaryMetricsResultsLoading', 'currentProjectId'],
            modalsLogic,
            ['isRunningTimeConfigModalOpen'],
        ],
        actions: [
            experimentLogic({ experimentId: props.experimentId, tabId: props.tabId }),
            ['updateExperiment', 'setExperiment'],
            modalsLogic,
            ['closeRunningTimeConfigModal'],
        ],
    })),

    actions({
        setConfig: (config: Partial<RunningTimeConfig>) => ({ config }),
        resetConfig: true,
        save: true,
        cancel: true,
        persistRunningTimeEstimate: true,
    }),

    reducers({
        configOverrides: [
            null as Partial<RunningTimeConfig> | null,
            {
                setConfig: (state, { config }) => ({ ...state, ...config }),
                resetConfig: () => null,
            },
        ],
    }),

    selectors({
        numberOfVariants: [
            (s) => [s.experiment],
            (experiment): number => experiment?.feature_flag?.filters?.multivariate?.variants?.length ?? 2,
        ],

        isManualMode: [
            (s) => [s.experiment],
            (experiment): boolean =>
                experiment?.parameters?.exposure_estimate_config?.conversionRateInputType ===
                ConversionRateInputType.MANUAL,
        ],

        initialConfig: [
            (s) => [s.experiment, s.isManualMode],
            (experiment, isManualMode): RunningTimeConfig => ({
                mode: isManualMode ? 'manual' : 'automatic',
                mde: experiment?.parameters?.minimum_detectable_effect ?? DEFAULT_MDE,
                metricType:
                    (experiment?.parameters?.exposure_estimate_config
                        ?.manualMetricType as ManualCalculatorMetricType) ?? 'funnel',
                baselineValue: experiment?.parameters?.exposure_estimate_config?.manualBaselineValue ?? 5,
                exposureRate: experiment?.parameters?.exposure_estimate_config?.manualExposureRate ?? 100,
            }),
        ],

        config: [
            (s) => [s.initialConfig, s.configOverrides],
            (initialConfig, configOverrides): RunningTimeConfig =>
                configOverrides ? { ...initialConfig, ...configOverrides } : initialConfig,
        ],

        currentExposures: [
            (s) => [s.orderedPrimaryMetricsWithResults],
            (results): number | null => calculateCurrentExposures(results?.[0]?.result ?? null),
        ],
        targetSampleSize: [
            (s) => [s.isManualMode, s.experiment, s.orderedPrimaryMetricsWithResults, s.numberOfVariants, s.config],
            (isManualMode, experiment, results, numberOfVariants, config): number | null => {
                if (isManualMode) {
                    const saved = experiment?.parameters?.exposure_estimate_config
                    const baseline = saved?.manualBaselineValue ?? 0
                    if (baseline <= 0) {
                        return null
                    }
                    const metricType = (saved?.manualMetricType as ManualCalculatorMetricType) ?? 'funnel'
                    const adjustedBaseline = metricType === 'funnel' ? baseline / 100 : baseline
                    const mde = experiment?.parameters?.minimum_detectable_effect ?? DEFAULT_MDE
                    return calculateSampleSize(metricType, adjustedBaseline, mde, numberOfVariants)
                }

                // Automatic mode: calculate from live experiment data
                const firstMetric = results?.[0]
                if (!firstMetric?.metric || !firstMetric?.result?.baseline) {
                    return null
                }
                const baselineValue = calculateBaselineValue(firstMetric.result.baseline, firstMetric.metric)
                if (baselineValue === null) {
                    return null
                }
                return calculateRecommendedSampleSize(
                    firstMetric.metric,
                    config.mde,
                    baselineValue,
                    numberOfVariants,
                    firstMetric.result.baseline
                )
            },
        ],

        dailyExposureRate: [
            (s) => [s.isManualMode, s.experiment, s.currentExposures],
            (isManualMode, experiment, currentExposures): number | null => {
                if (isManualMode) {
                    return experiment?.parameters?.exposure_estimate_config?.manualExposureRate ?? null
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
            (s) => [s.config, s.numberOfVariants],
            (config, numberOfVariants): { sampleSize: number | null; runningTime: number | null } => {
                // Use !(x > 0) to catch NaN, 0, negative, and undefined
                if (config.mode !== 'manual' || !(config.baselineValue > 0)) {
                    return { sampleSize: null, runningTime: null }
                }

                const baselineValue = config.metricType === 'funnel' ? config.baselineValue / 100 : config.baselineValue
                const sampleSize = calculateSampleSize(config.metricType, baselineValue, config.mde, numberOfVariants)

                if (!sampleSize || !(config.exposureRate > 0)) {
                    return { sampleSize, runningTime: null }
                }

                const runningTime = Math.ceil(sampleSize / config.exposureRate)
                return { sampleSize, runningTime }
            },
        ],
    }),

    subscriptions(({ actions }) => ({
        primaryMetricsResultsLoading: (loading: boolean) => {
            if (!loading) {
                actions.persistRunningTimeEstimate()
            }
        },
    })),

    listeners(({ actions, values, props }) => ({
        persistRunningTimeEstimate: async () => {
            const { isManualMode, remainingDays, targetSampleSize, experiment, currentProjectId } = values

            if (isManualMode || !experiment?.start_date || remainingDays === null || targetSampleSize === null) {
                return
            }

            const savedRunningTime = experiment?.parameters?.recommended_running_time
            const savedSampleSize = experiment?.parameters?.recommended_sample_size
            if (savedRunningTime === remainingDays && savedSampleSize === targetSampleSize) {
                return
            }

            const updatedParameters = {
                ...experiment?.parameters,
                recommended_running_time: remainingDays,
                recommended_sample_size: targetSampleSize,
            }

            await api.update(`api/projects/${currentProjectId}/experiments/${props.experimentId}`, {
                parameters: updatedParameters,
            })

            actions.setExperiment({ parameters: updatedParameters })
        },

        save: () => {
            const { config, numberOfVariants, experiment } = values

            if (config.mode === 'manual') {
                // Convert NaN (from empty input) to 0
                const manualBaselineValue = Number.isNaN(config.baselineValue) ? 0 : config.baselineValue
                const manualExposureRate = Number.isNaN(config.exposureRate) ? 0 : config.exposureRate

                const baselineValue = config.metricType === 'funnel' ? manualBaselineValue / 100 : manualBaselineValue
                const sampleSize = calculateSampleSize(config.metricType, baselineValue, config.mde, numberOfVariants)
                const runningTime =
                    sampleSize && manualExposureRate > 0 ? Math.ceil(sampleSize / manualExposureRate) : null

                actions.updateExperiment({
                    parameters: {
                        ...experiment?.parameters,
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
                })
            } else {
                actions.updateExperiment({
                    parameters: {
                        ...experiment?.parameters,
                        minimum_detectable_effect: config.mde,
                        exposure_estimate_config: {
                            conversionRateInputType: ConversionRateInputType.AUTOMATIC,
                        },
                    },
                })
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
