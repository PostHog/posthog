import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { ScatterChart, TooltipFooter, TooltipSurface, TooltipSwatch } from '@posthog/quill-charts'
import type { ScatterChartConfig, ScatterPoint, ScatterSeries } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { type SearchPoint, formatDelta, searchYDomain } from '../agentSearch'
import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { AgentSearchOverlay } from './AgentSearchOverlay'
import { EXPERIMENT_STATUS } from './experimentStatus'
import { SectionCard } from './SectionCard'

// Room above the plot for the run band labels.
const CHART_MARGINS = { top: 24 }

/** Tells the logic which point the tooltip shows, so the plain line can render under the chart. */
function HoveredPoint({ point }: { point: SearchPoint }): null {
    const { setHoveredSearchPoint } = useActions(autoresearchPipelineLogic)
    useEffect(() => {
        setHoveredSearchPoint(point)
        return () => setHoveredSearchPoint(null)
    }, [point, setHoveredSearchPoint])
    return null
}

/** Every experiment across runs: holdout AUC by status, the best score so far, run bands, the live model and its realized AUC. */
export function AgentSearchChart(): JSX.Element | null {
    const { agentSearch, champion, hoveredSearchPoint } = useValues(autoresearchPipelineLogic)
    const { searchPointClicked } = useActions(autoresearchPipelineLogic)
    const theme = useChartTheme()
    const liveRealized = champion?.realized_score ?? null

    const { series, config } = useMemo(() => {
        const points = agentSearch.points
        const yDomain = searchYDomain(points, liveRealized)
        const toPoint = (p: SearchPoint): ScatterPoint<SearchPoint> => ({
            x: p.seq,
            y: p.holdoutScore ?? yDomain[0],
            label: `Run ${p.runNumber} · experiment ${p.iterationNumber}`,
            meta: p,
        })
        const series: ScatterSeries<SearchPoint>[] = [
            {
                key: 'kept',
                label: EXPERIMENT_STATUS.kept.label,
                color: EXPERIMENT_STATUS.kept.color,
                points: points.filter((p) => p.status === 'kept' && p.holdoutScore != null).map(toPoint),
            },
            {
                key: 'discarded',
                label: EXPERIMENT_STATUS.discarded.label,
                color: EXPERIMENT_STATUS.discarded.color,
                pointRadius: 3,
                points: points.filter((p) => p.status === 'discarded' && p.holdoutScore != null).map(toPoint),
            },
            {
                key: 'crashed',
                label: EXPERIMENT_STATUS.crashed.label,
                color: EXPERIMENT_STATUS.crashed.color,
                shape: 'cross',
                points: points.filter((p) => p.status === 'crashed' || p.holdoutScore == null).map(toPoint),
            },
        ]
        const config: ScatterChartConfig<SearchPoint> = {
            xAxis: {
                domain: [0.5, points.length + 0.5],
                label: 'Experiment',
                tickFormatter: (value) => (Number.isInteger(value) ? String(value) : ''),
            },
            yAxis: { domain: yDomain, label: 'AUC in training', tickFormatter: (value) => value.toFixed(2) },
            legend: { show: true },
            margins: CHART_MARGINS,
        }
        return { series, config }
    }, [agentSearch, liveRealized])

    if (agentSearch.points.length === 0) {
        return null
    }

    return (
        <SectionCard
            title="How the agent got here"
            description={
                liveRealized != null
                    ? 'Each dot is one experiment, scored in training. The agent keeps a change only when it improves the score. The dashed line is the live model on real outcomes.'
                    : 'Each dot is one experiment, scored in training. The agent keeps a change only when it improves the score.'
            }
        >
            <div className="h-64 min-w-0 flex flex-col">
                <ScatterChart
                    series={series}
                    theme={theme}
                    config={config}
                    dataAttr="autoresearch-search-chart"
                    onPointClick={(point) => point.meta && searchPointClicked(point.meta)}
                    tooltip={({ point }) => {
                        const p = point.meta
                        if (!p) {
                            return null
                        }
                        const delta = formatDelta(p.delta)
                        return (
                            <TooltipSurface data-attr="autoresearch-search-chart-tooltip">
                                <HoveredPoint point={p} />
                                <div className="font-semibold text-sm">{`Run ${p.runNumber} · experiment ${p.iterationNumber}`}</div>
                                <div className="flex items-center gap-2 mt-1">
                                    <TooltipSwatch color={point.color} />
                                    <span>{EXPERIMENT_STATUS[p.status].label}</span>
                                    {p.holdoutScore != null && (
                                        <strong className="tabular-nums">{p.holdoutScore.toFixed(3)}</strong>
                                    )}
                                    {delta && <span className="opacity-70">{delta}</span>}
                                </div>
                                <TooltipFooter>Click to open the experiment</TooltipFooter>
                            </TooltipSurface>
                        )
                    }}
                >
                    <AgentSearchOverlay search={agentSearch} liveRealized={liveRealized} />
                </ScatterChart>
            </div>
            <div className="text-sm min-h-5 truncate" data-attr="autoresearch-search-chart-hovered">
                {hoveredSearchPoint ? (
                    <>
                        <span className="text-muted">{`Run ${hoveredSearchPoint.runNumber} · #${hoveredSearchPoint.iterationNumber}: `}</span>
                        {hoveredSearchPoint.summary || 'No description'}
                    </>
                ) : (
                    <span className="text-muted">
                        Point at a dot to read what the agent tried. Click it to open the experiment.
                    </span>
                )}
            </div>
        </SectionCard>
    )
}
