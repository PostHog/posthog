// DEPRECATED: This file has been deprecated in favor of FunnelBarGraph.tsx
import React, { useRef, useEffect, useState } from 'react'
import FunnelGraph from 'funnel-graph-js'
import { Loading, humanFriendlyDuration } from 'lib/utils'
import { useActions, useValues, BindLogic } from 'kea'
import { funnelLogic } from './funnelLogic'
import { ACTIONS_LINE_GRAPH_LINEAR, FEATURE_FLAGS } from 'lib/constants'
import { LineGraph } from 'scenes/insights/LineGraph'
import { FunnelBarGraph } from './FunnelBarGraph'
import { router } from 'kea-router'
import { InputNumber, Row } from 'antd'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { ChartDisplayType, ChartParams, FunnelStep } from '~/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FunnelHistogram } from './FunnelHistogram'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { FunnelEmptyState } from 'scenes/insights/EmptyStates'

import './FunnelViz.scss'

interface FunnelVizProps extends Omit<ChartParams, 'view'> {
    steps: FunnelStep[]
    timeConversionBins: number[]
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
    const {
        results: stepsResult,
        resultsLoading: funnelLoading,
        filters,
        conversionWindowInDays,
        areFiltersValid,
    } = useValues(logic)
    const { loadResults: loadFunnel, loadConversionWindow } = useActions(logic)
    const { loadPeople } = useActions(personsModalLogic)
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
                            step.average_conversion_time
                                ? 'Avg Time: ' + humanFriendlyDuration(step.average_conversion_time) || ''
                                : ''
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

    // Leave this at top. All filter visualizations require > 1 action or event filter
    if (!areFiltersValid) {
        return (
            <BindLogic logic={funnelLogic} props={{ dashboardItemId, cachedResults, filters: defaultFilters }}>
                <FunnelEmptyState />
            </BindLogic>
        )
    }

    if (filters.display === ACTIONS_LINE_GRAPH_LINEAR) {
        return steps && steps.length > 0 && steps[0].labels ? (
            <>
                <Row style={{ marginTop: -16, justifyContent: 'center' }}>
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
                </Row>
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
                    onClick={
                        dashboardItemId
                            ? null
                            : (point) => {
                                  loadPeople({
                                      action: { id: point.index, name: point.label, properties: [], type: 'actions' },
                                      label: point.label,
                                      date_from: point.day,
                                      date_to: point.day,
                                      filters: filters,
                                      saveOriginal: true,
                                  })
                              }
                    }
                />
            </>
        ) : null
    }
    if (featureFlags[FEATURE_FLAGS.FUNNEL_BAR_VIZ] && filters.display == ChartDisplayType.FunnelsTimeToConvert) {
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
