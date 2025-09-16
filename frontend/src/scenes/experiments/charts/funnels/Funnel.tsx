import '../../../funnels/Funnel.scss'

import { createContext, useContext, useMemo } from 'react'

import {
    ChartParams,
    FunnelStepReference,
    FunnelStepWithConversionMetrics,
    FunnelStepWithNestedBreakdown,
} from '~/types'

import { FunnelBarVertical } from './FunnelBarVertical'
import { FunnelDataProcessingOptions, processFunnelData } from './funnelDataUtils'

export interface FunnelProps extends ChartParams {
    /** Raw funnel step data */
    steps: FunnelStepWithNestedBreakdown[]
    /** Step reference for conversion calculations - defaults to total */
    stepReference?: FunnelStepReference
    /** Breakdowns to hide from legend */
    hiddenLegendBreakdowns?: string[]
    /** Disable baseline for experiments */
    disableBaseline?: boolean
}

export interface FunnelDataContext {
    visibleStepsWithConversionMetrics: FunnelStepWithConversionMetrics[]
    stepsWithConversionMetrics: FunnelStepWithConversionMetrics[]
    steps: FunnelStepWithNestedBreakdown[]
    hasFunnelResults: boolean
}

const FunnelDataContext = createContext<FunnelDataContext | null>(null)

export function useFunnelData(): FunnelDataContext {
    const context = useContext(FunnelDataContext)
    if (!context) {
        throw new Error('useFunnelData must be used within a experiment Funnel')
    }
    return context
}

/**
 * A data-driven funnel visualization component that accepts direct data instead of requiring a query.
 * This allows reusing the funnel visualization logic in contexts where you have the data but not a query,
 * such as in experiments or other custom use cases.
 */
export function Funnel({
    steps,
    stepReference = FunnelStepReference.total,
    hiddenLegendBreakdowns = [],
    disableBaseline = false,
    inCardView = false,
    ...chartParams
}: FunnelProps): JSX.Element {
    const processedData = useMemo(() => {
        const options: FunnelDataProcessingOptions = {
            stepReference,
            disableBaseline,
            hiddenLegendBreakdowns,
        }
        return processFunnelData(steps, options)
    }, [steps, stepReference, disableBaseline, hiddenLegendBreakdowns])

    const contextValue: FunnelDataContext = useMemo(
        () => ({
            visibleStepsWithConversionMetrics: processedData.visibleStepsWithConversionMetrics,
            stepsWithConversionMetrics: processedData.stepsWithConversionMetrics,
            steps: processedData.steps,
            hasFunnelResults: processedData.hasFunnelResults,
        }),
        [processedData]
    )

    return (
        <FunnelDataContext.Provider value={contextValue}>
            <div className={`FunnelInsight FunnelInsight--type-steps-vertical${inCardView ? ' InsightCard' : ''}`}>
                <FunnelBarVertical {...chartParams} inCardView={inCardView} />
            </div>
        </FunnelDataContext.Provider>
    )
}
