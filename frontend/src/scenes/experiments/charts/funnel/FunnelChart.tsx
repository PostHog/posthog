import '../../../funnels/Funnel.scss'

import { createContext, useContext, useMemo } from 'react'

import { ExperimentMetric, NewExperimentQueryResponse } from '~/queries/schema/schema-general'
import {
    ChartParams,
    Experiment,
    FunnelStepReference,
    FunnelStepWithConversionMetrics,
    FunnelStepWithNestedBreakdown,
} from '~/types'

import { FunnelBarVertical } from './FunnelBarVertical'
import { FunnelDataProcessingOptions, processFunnelData } from './funnelUtils'

export interface FunnelChartProps extends ChartParams {
    /** Raw funnel step data */
    steps: FunnelStepWithNestedBreakdown[]
    /** Step reference for conversion calculations - defaults to total */
    stepReference?: FunnelStepReference
    /** Breakdowns to hide from legend */
    hiddenLegendBreakdowns?: string[]
    /** Disable baseline for experiments */
    disableBaseline?: boolean
    /** Experiment result data */
    experimentResult: NewExperimentQueryResponse
    experiment?: Experiment
    /** Experiment metric configuration */
    metric?: ExperimentMetric
}

export interface FunnelChartDataContext {
    stepsWithConversionMetrics: FunnelStepWithConversionMetrics[]
    steps: FunnelStepWithNestedBreakdown[]
    hasFunnelResults: boolean
    experimentResult: NewExperimentQueryResponse
    experiment?: Experiment
    metric?: ExperimentMetric
}

const FunnelChartDataContext = createContext<FunnelChartDataContext | null>(null)

export function useFunnelChartData(): FunnelChartDataContext {
    const context = useContext(FunnelChartDataContext)
    if (!context) {
        throw new Error('useFunnelChartData must be used within a experiment Funnel')
    }
    return context
}

/**
 * A data-driven funnel visualization component that accepts direct data instead of requiring a query.
 * This allows reusing the funnel visualization logic in where we have the data but not a query.
 * That is the case for experiments.
 */
export function FunnelChart({
    steps,
    stepReference = FunnelStepReference.total,
    hiddenLegendBreakdowns = [],
    disableBaseline = false,
    inCardView = false,
    experimentResult,
    experiment,
    metric,
    ...chartParams
}: FunnelChartProps): JSX.Element {
    const processedData = useMemo(() => {
        const options: FunnelDataProcessingOptions = {
            stepReference,
            disableBaseline,
            hiddenLegendBreakdowns,
        }
        return processFunnelData(steps, options)
    }, [steps, stepReference, disableBaseline, hiddenLegendBreakdowns])

    const contextValue: FunnelChartDataContext = useMemo(
        () => ({
            stepsWithConversionMetrics: processedData.stepsWithConversionMetrics,
            steps: processedData.steps,
            hasFunnelResults: processedData.hasFunnelResults,
            experimentResult,
            experiment,
            metric,
        }),
        [processedData, experimentResult, experiment, metric]
    )

    return (
        <FunnelChartDataContext.Provider value={contextValue}>
            <div className={`pt-4 FunnelInsight FunnelInsight--type-steps-vertical${inCardView ? ' InsightCard' : ''}`}>
                <FunnelBarVertical {...chartParams} inCardView={inCardView} />
            </div>
        </FunnelChartDataContext.Provider>
    )
}
