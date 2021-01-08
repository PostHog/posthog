import React, { useRef, useEffect, useState } from 'react'
import FunnelGraph from 'funnel-graph-js'
import { Loading, humanFriendlyDuration } from 'lib/utils'
import { useActions, useValues } from 'kea'
import { funnelVizLogic } from 'scenes/funnels/funnelVizLogic'
import './FunnelViz.scss'

export function FunnelViz({ steps: stepsParam, dashboardItemId, cachedResults }) {
    const container = useRef(null)
    const [steps, setSteps] = useState(stepsParam)
    const logic = funnelVizLogic({ dashboardItemId, cachedResults })
    const { results: stepsResult, resultsLoading: funnelLoading } = useValues(logic)
    const { loadResults: loadFunnel } = useActions(logic)

    function buildChart() {
        if (!steps || steps.length === 0) {
            return
        }
        if (container.current) {
            container.current.innerHTML = ''
        }
        let graph = new FunnelGraph({
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
        if (stepsResult && !stepsParam) {
            setSteps(stepsResult)
            buildChart()
        }
    }, [stepsResult, funnelLoading])

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
