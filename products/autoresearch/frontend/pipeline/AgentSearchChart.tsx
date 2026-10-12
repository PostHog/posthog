import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { ScatterChart, TooltipFooter, TooltipSurface, TooltipSwatch } from '@posthog/quill-charts'
import type { ScatterChartConfig, ScatterPoint, ScatterSeries } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { type SearchPoint, formatDelta, searchYDomain } from '../agentSearch'
import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { AgentSearchOverlay } from './AgentSearchOverlay'

const STATUS_LABEL: Record<SearchPoint['status'], string> = {
    kept: 'Kept',
    discarded: 'Discarded',
    crashed: 'Crashed',
}

// Room above the plot for the run band labels.
const CHART_MARGINS = { top: 24 }

/** Every experiment across runs: holdout AUC by status, the best score so far, run bands and the live model. */
export function AgentSearchChart(): JSX.Element | null {
    const { agentSearch } = useValues(autoresearchPipelineLogic)
    const { searchPointClicked } = useActions(autoresearchPipelineLogic)
    const theme = useChartTheme()

    const { series, config } = useMemo(() => {
        const points = agentSearch.points
        const yDomain = searchYDomain(points)
        const toPoint = (p: SearchPoint): ScatterPoint<SearchPoint> => ({
            x: p.seq,
            y: p.holdoutScore ?? yDomain[0],
            label: `Run ${p.runNumber} · experiment ${p.iterationNumber}`,
            meta: p,
        })
        const series: ScatterSeries<SearchPoint>[] = [
            {
                key: 'kept',
                label: 'Kept',
                color: 'var(--success)',
                points: points.filter((p) => p.status === 'kept' && p.holdoutScore != null).map(toPoint),
            },
            {
                key: 'discarded',
                label: 'Discarded',
                color: 'var(--color-text-secondary)',
                pointRadius: 3,
                points: points.filter((p) => p.status === 'discarded' && p.holdoutScore != null).map(toPoint),
            },
            {
                key: 'crashed',
                label: 'Crashed',
                color: 'var(--danger)',
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
            yAxis: { domain: yDomain, label: 'Holdout AUC', tickFormatter: (value) => value.toFixed(2) },
            legend: { show: true },
            margins: CHART_MARGINS,
        }
        return { series, config }
    }, [agentSearch])

    if (agentSearch.points.length === 0) {
        return null
    }

    return (
        <div className="border rounded p-3 space-y-2">
            <div>
                <div className="text-sm font-semibold">How the agent found it</div>
                <div className="text-xs text-muted">
                    Each dot is one experiment. The agent keeps a change only when it beats the best score so far.
                </div>
            </div>
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
                                <div className="font-semibold text-sm">{`Run ${p.runNumber} · experiment ${p.iterationNumber}`}</div>
                                <div className="flex items-center gap-2 mt-1">
                                    <TooltipSwatch color={point.color} />
                                    <span>{STATUS_LABEL[p.status]}</span>
                                    {p.holdoutScore != null && (
                                        <strong className="tabular-nums">{`AUC ${p.holdoutScore.toFixed(3)}`}</strong>
                                    )}
                                    {delta && <span className="opacity-70">{delta}</span>}
                                </div>
                                {p.agentDescription && (
                                    <div className="mt-1 max-w-80 break-words opacity-80">{p.agentDescription}</div>
                                )}
                                <TooltipFooter>Click to open this run in the log</TooltipFooter>
                            </TooltipSurface>
                        )
                    }}
                >
                    <AgentSearchOverlay search={agentSearch} />
                </ScatterChart>
            </div>
        </div>
    )
}
