import React, { useRef, useEffect, useState } from 'react'
import FunnelGraph from 'funnel-graph-js'
import { Loading, humanFriendlyDuration } from 'lib/utils'
import { useActions, useValues } from 'kea'
import './FunnelViz.scss'
import { funnelLogic } from './funnelLogic'
import { ACTIONS_LINE_GRAPH_LINEAR, FEATURE_FLAGS } from 'lib/constants'
import { LineGraph } from 'scenes/insights/LineGraph'
import { FunnelBarGraph } from './FunnelBarGraph'
import { router } from 'kea-router'
import { IllustrationDanger } from 'lib/components/icons'
import { InputNumber } from 'antd'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { ChartDisplayType, ChartParams, FunnelStep } from '~/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FunnelHistogram } from './FunnelHistogram'

interface FunnelVizProps extends Omit<ChartParams, 'view'> {
    steps: FunnelStep[]
    timeConversionBins: any[]
}

export function FunnelViz({
    steps: stepsParam,
    filters: defaultFilters,
    timeConversionBins,
    dashboardItemId,
    cachedResults,
    inSharedMode,
    color = 'white',
}: FunnelVizProps): JSX.Element | null {
    const container = useRef<HTMLDivElement | null>(null)
    const [steps, setSteps] = useState(stepsParam)
    const logic = funnelLogic({ dashboardItemId, cachedResults, filters: defaultFilters })
    const { results: stepsResult, resultsLoading: funnelLoading, filters, conversionWindowInDays } = useValues(logic)
    const { loadResults: loadFunnel, loadConversionWindow } = useActions(logic)
    const [{ fromItem }] = useState(router.values.hashParams)
    const { preflight } = useValues(preflightLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    function buildChart(): void {
        // Build and mount graph for default "flow" visualization.
        // If steps are empty, new bargraph view is active, or linechart is visible, don't render flow graph.
        if (
            !steps ||
            steps.length === 0 ||
            featureFlags[FEATURE_FLAGS.FUNNEL_BAR_VIZ] ||
            filters.display === ACTIONS_LINE_GRAPH_LINEAR
        ) {
            return
        }
        if (container.current) {
            container.current.innerHTML = ''
        }
        const graph = new FunnelGraph({
            container: '.funnel-graph',
            data: {
                labels: steps.map(
                    (step) =>
                        `${step.name} (${step.count})  ${
                            step.average_time ? 'Avg Time: ' + humanFriendlyDuration(step.average_time) || '' : ''
                        }`
                ),
                values: steps.map((step) => step.count),
                colors: ['#66b0ff', 'var(--primary)'],
            },
            displayPercent: true,
        })
        graph.createContainer = () => {}
        graph.container = container.current
        graph.graphContainer = document.createElement('div')
        graph.graphContainer.classList.add('svg-funnel-js__container')

        if (graph.container) {
            graph.container.appendChild(graph.graphContainer)
            graph.draw()
        }
    }

    useEffect(() => {
        if (stepsParam) {
            buildChart()
        } else {
            loadFunnel()
        }

        window.addEventListener('resize', buildChart)
        return window.removeEventListener('resize', buildChart)
    }, [])

    useEffect(() => {
        buildChart()
    }, [steps])

    useEffect(() => {
        setSteps(stepsParam)
    }, [stepsParam])

    useEffect(() => {
        if (stepsResult) {
            setSteps(stepsResult)
            buildChart()
        }
    }, [stepsResult, funnelLoading])

    if (filters.display === ACTIONS_LINE_GRAPH_LINEAR) {
        if ((filters.events?.length || 0) + (filters.actions?.length || 0) == 1) {
            return (
                <div className="insight-empty-state error-message">
                    <div className="illustration-main">
                        <IllustrationDanger />
                    </div>
                    <h3 className="l3">You can only use funnel trends with more than one funnel step.</h3>
                </div>
            )
        }
        return steps && steps.length > 0 && steps[0].labels ? (
            <>
                <div style={{ position: 'absolute', marginTop: -20, textAlign: 'center', width: '90%' }}>
                    {preflight?.is_clickhouse_enabled && (
                        <>
                            converted within&nbsp;
                            <InputNumber
                                size="small"
                                min={1}
                                max={365}
                                defaultValue={conversionWindowInDays}
                                onChange={(days) => loadConversionWindow(Number(days))}
                            />
                            &nbsp;days =&nbsp;
                        </>
                    )}
                    % converted from first to last step
                </div>
                <LineGraph
                    data-attr="trend-line-graph-funnel"
                    type="line"
                    color={color}
                    datasets={steps}
                    labels={steps[0].labels}
                    isInProgress={!filters.date_to}
                    dashboardItemId={dashboardItemId || fromItem}
                    inSharedMode={inSharedMode}
                    percentage={true}
                />
            </>
        ) : null
    }
    if (filters.display == ChartDisplayType.FunnelsHistogram) {
        return timeConversionBins && timeConversionBins.length > 0 ? <FunnelHistogram /> : null
    }

    if (featureFlags[FEATURE_FLAGS.FUNNEL_BAR_VIZ]) {
        return steps && steps.length > 0 ? <FunnelBarGraph steps={steps} /> : null
    }

    return !funnelLoading ? (
        steps && steps.length > 0 ? (
            <div
                data-attr="funnel-viz"
                ref={container}
                className="svg-funnel-js"
                style={{ height: '100%', width: '100%', overflow: 'hidden' }}
            />
        ) : (
            <p style={{ margin: '1rem' }}>This funnel doesn't have any steps. </p>
        )
    ) : (
        <Loading />
    )
}
