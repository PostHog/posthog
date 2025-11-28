import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { ConversionRateInputType, Experiment } from '~/types'

import { DEFAULT_MDE, experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import {
    MetricMathType,
    calculateCurrentExposures,
    calculateDaysElapsed,
    calculateExperimentTimeEstimate,
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
    metricType: MetricMathType
    baselineValue: number
    exposureRate: number
}

export interface ExperimentData {
    estimatedRemainingDays: number | null
    exposures: number | null
    recommendedSampleSize: number | null
    exposureRate: number | null
}

export interface DisplayValues {
    estimatedDays: number | null
    exposures: number | null
    sampleSize: number | null
}

export const runningTimeLogic = kea<runningTimeLogicType>([
    path(['scenes', 'experiments', 'RunningTimeCalculatorNew', 'runningTimeLogic']),
    props({} as RunningTimeLogicProps),
    key((props) => `${props.experimentId}-${props.tabId}`),

    connect((props: RunningTimeLogicProps) => ({
        values: [
            experimentLogic({ experimentId: props.experimentId, tabId: props.tabId }),
            ['experiment', 'orderedPrimaryMetricsWithResults', 'primaryMetricsResultsLoading'],
            modalsLogic,
            ['isRunningTimeConfigModalOpen'],
        ],
        actions: [
            experimentLogic({ experimentId: props.experimentId, tabId: props.tabId }),
            ['updateExperiment'],
            modalsLogic,
            ['closeRunningTimeConfigModal'],
        ],
    })),

    actions({
        setConfig: (config: Partial<RunningTimeConfig>) => ({ config }),
        resetConfig: true,
        save: true,
        cancel: true,
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
                    (experiment?.parameters?.exposure_estimate_config?.manualMetricType as MetricMathType) ?? 'funnel',
                baselineValue: experiment?.parameters?.exposure_estimate_config?.manualBaselineValue ?? 0,
                exposureRate: experiment?.parameters?.exposure_estimate_config?.manualExposureRate ?? 0,
            }),
        ],

        config: [
            (s) => [s.initialConfig, s.configOverrides],
            (initialConfig, configOverrides): RunningTimeConfig =>
                configOverrides ? { ...initialConfig, ...configOverrides } : initialConfig,
        ],

        experimentData: [
            (s) => [s.orderedPrimaryMetricsWithResults, s.experiment, s.config],
            (orderedPrimaryMetricsWithResults, experiment, config): ExperimentData | null => {
                const firstMetric = orderedPrimaryMetricsWithResults?.[0]

                if (!firstMetric?.metric || !firstMetric?.result?.baseline || !experiment?.start_date) {
                    return null
                }

                const daysElapsed = calculateDaysElapsed(experiment.start_date)
                const currentExposures = calculateCurrentExposures(firstMetric.result)

                if (!daysElapsed || daysElapsed < 1 || !currentExposures || currentExposures < 100) {
                    return null
                }

                const estimates = calculateExperimentTimeEstimate(
                    firstMetric.metric,
                    firstMetric.result,
                    experiment,
                    config.mde
                )

                return {
                    estimatedRemainingDays: estimates.estimatedRemainingDays,
                    exposures: estimates.currentExposures,
                    recommendedSampleSize: estimates.recommendedSampleSize,
                    exposureRate: estimates.exposureRate,
                }
            },
        ],

        displayValues: [
            (s) => [s.isManualMode, s.experimentData, s.experiment, s.numberOfVariants],
            (isManualMode, experimentData, experiment, numberOfVariants): DisplayValues => {
                const currentExposures = experimentData?.exposures ?? null

                if (!isManualMode) {
                    return {
                        estimatedDays: experimentData?.estimatedRemainingDays ?? null,
                        exposures: currentExposures,
                        sampleSize: experimentData?.recommendedSampleSize ?? null,
                    }
                }

                const savedConfig = experiment?.parameters?.exposure_estimate_config
                const baselineValue = savedConfig?.manualBaselineValue ?? 0
                const metricType = (savedConfig?.manualMetricType as MetricMathType) ?? 'funnel'
                const manualExposureRate = savedConfig?.manualExposureRate ?? 0

                if (baselineValue <= 0) {
                    return { estimatedDays: null, exposures: null, sampleSize: null }
                }

                const adjustedBaseline = metricType === 'funnel' ? baselineValue / 100 : baselineValue
                const mde = experiment?.parameters?.minimum_detectable_effect ?? DEFAULT_MDE
                const sampleSize = calculateSampleSize(metricType, adjustedBaseline, mde, numberOfVariants)

                if (!sampleSize) {
                    return { estimatedDays: null, exposures: currentExposures, sampleSize: null }
                }

                if (currentExposures !== null) {
                    if (currentExposures >= sampleSize) {
                        return { estimatedDays: 0, exposures: currentExposures, sampleSize }
                    }

                    if (manualExposureRate > 0) {
                        const remainingDays = Math.ceil((sampleSize - currentExposures) / manualExposureRate)
                        return { estimatedDays: remainingDays, exposures: currentExposures, sampleSize }
                    }
                }

                const totalTime = manualExposureRate > 0 ? Math.ceil(sampleSize / manualExposureRate) : null
                return { estimatedDays: totalTime, exposures: null, sampleSize }
            },
        ],

        manualResults: [
            (s) => [s.config, s.numberOfVariants],
            (config, numberOfVariants): { sampleSize: number | null; runningTime: number | null } => {
                if (config.mode !== 'manual' || config.baselineValue <= 0) {
                    return { sampleSize: null, runningTime: null }
                }

                const baselineValue = config.metricType === 'funnel' ? config.baselineValue / 100 : config.baselineValue
                const sampleSize = calculateSampleSize(config.metricType, baselineValue, config.mde, numberOfVariants)

                if (!sampleSize || config.exposureRate <= 0) {
                    return { sampleSize, runningTime: null }
                }

                const runningTime = Math.ceil(sampleSize / config.exposureRate)
                return { sampleSize, runningTime }
            },
        ],

        isComplete: [
            (s) => [s.displayValues],
            (displayValues): boolean =>
                displayValues.exposures !== null &&
                displayValues.sampleSize !== null &&
                displayValues.exposures >= displayValues.sampleSize,
        ],
    }),

    listeners(({ actions, values }) => ({
        save: () => {
            const { config, numberOfVariants, experiment } = values

            if (config.mode === 'manual') {
                const baselineValue = config.metricType === 'funnel' ? config.baselineValue / 100 : config.baselineValue
                const sampleSize = calculateSampleSize(config.metricType, baselineValue, config.mde, numberOfVariants)
                const runningTime =
                    sampleSize && config.exposureRate > 0 ? Math.ceil(sampleSize / config.exposureRate) : null

                actions.updateExperiment({
                    parameters: {
                        ...experiment?.parameters,
                        minimum_detectable_effect: config.mde,
                        recommended_sample_size: sampleSize ?? undefined,
                        recommended_running_time: runningTime ?? undefined,
                        exposure_estimate_config: {
                            conversionRateInputType: ConversionRateInputType.MANUAL,
                            manualMetricType: config.metricType,
                            manualBaselineValue: config.baselineValue,
                            manualExposureRate: config.exposureRate,
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
