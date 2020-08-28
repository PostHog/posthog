import React, { useRef, useEffect, useState } from 'react'
import FunnelGraph from 'funnel-graph-js'
import { Link } from 'lib/components/Link'
import { Loading, humanFriendlyDuration, toParams } from 'lib/utils'
import PropTypes from 'prop-types'
import { useValues, useActions } from 'kea'
import { funnelVizLogic } from 'scenes/funnels/funnelVizLogic'
import { LineGraph } from 'scenes/insights/LineGraph'
import { router } from 'kea-router'

export function FunnelSteps({ funnel: funnelProp, dashboardItemId, funnelId }) {
    const container = useRef()
    const [funnel, setFunnel] = useState(funnelProp)
    const logic = funnelVizLogic({ funnelId, dashboardItemId })
    const { stepsResults, stepsResultsLoading } = useValues(logic)
    const { loadSteps } = useActions(logic)

    function buildChart() {
        if (!funnel || funnel.steps.length == 0) return
        if (container.current) container.current.innerHTML = ''
        let graph = new FunnelGraph({
            container: '.funnel-graph',
            data: {
                labels: funnel.steps.map(
                    (step) =>
                        `${step.name} (${step.count})  ${
                            step.average_time ? 'Avg Time: ' + humanFriendlyDuration(step.average_time) || '' : ''
                        }`
                ),
                values: funnel.steps.map((step) => step.count),
                colors: ['#66b0ff', 'var(--blue)'],
            },
            displayPercent: true,
        })
        graph.createContainer = () => {}
        graph.container = container.current
        graph.graphContainer = document.createElement('div')
        graph.graphContainer.classList.add('svg-funnel-js__container')
        graph.container.appendChild(graph.graphContainer)

        graph.draw()
    }

    useEffect(() => {
        if (funnel) buildChart()
        else loadSteps()

        window.addEventListener('resize', buildChart)
        return window.removeEventListener('resize', buildChart)
    }, [])

    useEffect(() => {
        buildChart()
    }, [funnel])

    useEffect(() => {
        setFunnel(funnelProp)
    }, [funnelProp])

    useEffect(() => {
        if (stepsResults) {
            setFunnel(stepsResults)
        }
    }, [stepsResults])

    return funnel && !stepsResultsLoading ? (
        funnel.steps.length > 0 ? (
            <div
                data-attr="funnel-viz"
                ref={container}
                className="svg-funnel-js"
                style={{ height: '100%', width: '100%' }}
            ></div>
        ) : (
            <p style={{ margin: '1rem' }}>
                This funnel doesn't have any steps.{' '}
                <Link to={'/funnel/' + funnel.id}>Click here to add some steps.</Link>
            </p>
        )
    ) : (
        <Loading />
    )
}

FunnelSteps.propTypes = {
    funnel: PropTypes.object,
    funnelId: PropTypes.number,
}

export function FunnelLineGraph({ funnel: funnelProp, dashboardItemId, inSharedMode, color = 'white' }) {
    const [funnel, setFunnel] = useState(funnelProp)
    const logic = funnelVizLogic({ funnelId: funnel.id, dashboardItemId })
    const { trendsResults, trendsResultsLoading } = useValues(logic)
    const { loadTrends } = useActions(logic)
    const [{ fromItem }] = useState(router.values.hashParams)

    useEffect(() => {
        loadTrends()
    }, [toParams(funnel)])

    useEffect(() => {
        setFunnel(funnelProp)
    }, [funnelProp])

    useEffect(() => {
        if (trendsResults) {
            setFunnel(trendsResults)
        }
    }, [trendsResults])

    return trendsResults && !trendsResultsLoading ? (
        <LineGraph
            pageKey="trends-annotations"
            data-attr="trend-line-graph-funnel"
            type="line"
            color={color}
            datasets={trendsResults}
            labels={trendsResults.labels ?? []}
            isInProgress={!funnel.filters.date_to}
            dashboardItemId={dashboardItemId || fromItem}
            inSharedMode={inSharedMode}
        />
    ) : (
        <Loading />
    )
}
