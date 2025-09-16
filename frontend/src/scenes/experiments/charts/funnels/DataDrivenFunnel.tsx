import { createContext, useContext, useMemo } from 'react'

import { FunnelLayout } from 'lib/constants'

import {
    ChartParams,
    FunnelStepReference,
    FunnelStepWithConversionMetrics,
    FunnelStepWithNestedBreakdown,
    FunnelVizType,
    FunnelsTimeConversionBins,
    HistogramGraphDatum,
} from '~/types'

import '../../../funnels/Funnel'
import { DataDrivenFunnelBarVertical } from './DataDrivenFunnelBarVertical'
import { FunnelDataProcessingOptions, processFunnelData, processTimeConversionData } from './funnelDataUtils'

export interface DataDrivenFunnelProps extends ChartParams {
    /** Raw funnel step data */
    steps: FunnelStepWithNestedBreakdown[]
    /** Visualization type - defaults to Steps */
    vizType?: FunnelVizType
    /** Layout for steps visualization - defaults to vertical */
    layout?: FunnelLayout
    /** Step reference for conversion calculations - defaults to total */
    stepReference?: FunnelStepReference
    /** Breakdowns to hide from legend */
    hiddenLegendBreakdowns?: string[]
    /** Disable baseline for experiments */
    disableBaseline?: boolean
    /** Time conversion data for histogram visualization */
    timeConversionData?: FunnelsTimeConversionBins
}

export interface FunnelDataContext {
    visibleStepsWithConversionMetrics: FunnelStepWithConversionMetrics[]
    stepsWithConversionMetrics: FunnelStepWithConversionMetrics[]
    steps: FunnelStepWithNestedBreakdown[]
    histogramGraphData?: HistogramGraphDatum[] | null
    hasFunnelResults: boolean
    vizType: FunnelVizType
    layout: FunnelLayout
}

const FunnelDataContext = createContext<FunnelDataContext | null>(null)

export function useFunnelData(): FunnelDataContext {
    const context = useContext(FunnelDataContext)
    if (!context) {
        throw new Error('useFunnelData must be used within a DataDrivenFunnel')
    }
    return context
}

/**
 * A data-driven funnel visualization component that accepts direct data instead of requiring a query.
 * This allows reusing the funnel visualization logic in contexts where you have the data but not a query,
 * such as in experiments or other custom use cases.
 *
 * Usage:
 * ```tsx
 * <DataDrivenFunnel
 *   steps={funnelSteps}
 *   vizType={FunnelVizType.Steps}
 *   layout={FunnelLayout.vertical}
 *   showPersonsModal={true}
 * />
 * ```
 */
export function DataDrivenFunnel({
    steps,
    vizType = FunnelVizType.Steps,
    layout = FunnelLayout.vertical,
    stepReference = FunnelStepReference.total,
    hiddenLegendBreakdowns = [],
    disableBaseline = false,
    timeConversionData,
    inCardView = false,
    ...chartParams
}: DataDrivenFunnelProps): JSX.Element {
    // Process the raw data into the format needed by visualization components
    const processedData = useMemo(() => {
        const options: FunnelDataProcessingOptions = {
            stepReference,
            layout,
            disableBaseline,
            hiddenLegendBreakdowns,
        }
        return processFunnelData(steps, options)
    }, [steps, stepReference, layout, disableBaseline, hiddenLegendBreakdowns])

    // Process time conversion data if provided
    const histogramData = useMemo(() => {
        return timeConversionData ? processTimeConversionData(timeConversionData) : null
    }, [timeConversionData])

    // Create the context value
    const contextValue: FunnelDataContext = useMemo(
        () => ({
            visibleStepsWithConversionMetrics: processedData.visibleStepsWithConversionMetrics,
            stepsWithConversionMetrics: processedData.stepsWithConversionMetrics,
            steps: processedData.steps,
            histogramGraphData: histogramData,
            hasFunnelResults: processedData.hasFunnelResults,
            vizType,
            layout,
        }),
        [processedData, histogramData, vizType, layout]
    )

    // Render the appropriate visualization based on type
    let viz: JSX.Element | null = null

    if (layout === FunnelLayout.vertical) {
        viz = <DataDrivenFunnelBarVertical {...chartParams} inCardView={inCardView} />
    } else {
        return <div>DataDrivenFunnel visualization with layout {layout} is not supported</div>
    }

    return (
        <FunnelDataContext.Provider value={contextValue}>
            <div
                className={`FunnelInsight FunnelInsight--type-${vizType?.toLowerCase()}${
                    vizType === FunnelVizType.Steps ? '-' + layout : ''
                }${inCardView ? ' InsightCard' : ''}`}
            >
                {viz}
            </div>
        </FunnelDataContext.Provider>
    )
}
