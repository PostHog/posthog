import '../../../funnels/Funnel.scss'

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

import { FunnelBarVertical } from './FunnelBarVertical'
import { FunnelDataProcessingOptions, processFunnelData, processTimeConversionData } from './funnelDataUtils'

export interface FunnelProps extends ChartParams {
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
    vizType = FunnelVizType.Steps,
    layout = FunnelLayout.vertical,
    stepReference = FunnelStepReference.total,
    hiddenLegendBreakdowns = [],
    disableBaseline = false,
    timeConversionData,
    inCardView = false,
    ...chartParams
}: FunnelProps): JSX.Element {
    const processedData = useMemo(() => {
        const options: FunnelDataProcessingOptions = {
            stepReference,
            layout,
            disableBaseline,
            hiddenLegendBreakdowns,
        }
        return processFunnelData(steps, options)
    }, [steps, stepReference, layout, disableBaseline, hiddenLegendBreakdowns])

    const histogramData = useMemo(() => {
        return timeConversionData ? processTimeConversionData(timeConversionData) : null
    }, [timeConversionData])

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
        viz = <FunnelBarVertical {...chartParams} inCardView={inCardView} />
    } else {
        return <div>Funnel visualization with layout {layout} is not supported</div>
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
