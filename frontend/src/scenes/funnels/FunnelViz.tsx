// DEPRECATED: This file has been deprecated in favor of FunnelBarGraph.tsx
import React, { useRef, useEffect } from 'react'
import FunnelGraph from 'funnel-graph-js'
import { humanFriendlyDuration } from 'lib/utils'
import { useActions, useValues } from 'kea'
import { funnelLogic } from './funnelLogic'
import { ChartParams, FunnelVizType } from '~/types'
import './FunnelViz.scss'

export function FunnelViz({
    filters: defaultFilters,
    dashboardItemId,
    cachedResults,
}: Omit<ChartParams, 'view'>): JSX.Element | null {
    const container = useRef<HTMLDivElement | null>(null)
    const logic = funnelLogic({ dashboardItemId, cachedResults, filters: defaultFilters })
    const { results: stepsResult, steps, isLoading: funnelLoading, filters } = useValues(logic)
    const { loadResults: loadFunnel } = useActions(logic)

    function buildChart(): void {
        // Build and mount graph for default "flow" visualization.
        // If steps are empty, new bargraph view is active, or linechart is visible, don't render flow graph.
        if (!steps || steps.length === 0 || filters.funnel_viz_type === FunnelVizType.Trends) {
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
        if (steps && steps.length) {
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
        if (stepsResult) {
            buildChart()
        }
    }, [stepsResult, funnelLoading])

    return (
        <div
            data-attr="funnel-viz"
            ref={container}
            className="svg-funnel-js"
            style={{ height: '100%', width: '100%', overflow: 'hidden' }}
        />
    )
}
