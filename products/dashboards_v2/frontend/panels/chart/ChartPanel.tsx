import clsx from 'clsx'
import { useContext, useMemo } from 'react'

import type { ContentPanel } from '../../dashboard/dashboardTypes'
import { PanelLoading } from '../PanelLoading'
import { TimeRangeContext } from '../timeRangeContext'
import { type ChartConfig, chartTargets } from './chartSpec'
import { type TargetFailure, combineTargetResults } from './targetResults'
import { useQueryFrames } from './useQueryFrames'
import type { ChartStates, DataFrame, RunQuery, VizDefinition } from './vizTypes'

function Message({ children }: { children: string }): JSX.Element {
    return <div className="flex h-full items-center justify-center text-center text-secondary text-sm">{children}</div>
}

function DefaultEmpty(): JSX.Element {
    return <Message>This query returned no results.</Message>
}

function DefaultError({ message }: { message: string }): JSX.Element {
    return <Message>{`Couldn't run this query. ${message}`}</Message>
}

function TargetFailures({ failures }: { failures: TargetFailure[] }): JSX.Element | null {
    if (failures.length === 0) {
        return null
    }
    return (
        <ul className="m-0 flex list-none flex-col gap-0.5 p-0 text-xs text-danger">
            {failures.map(({ refId, message }) => (
                <li key={refId} className="truncate" title={message}>
                    {`Query ${refId} couldn't run. ${message}`}
                </li>
            ))}
        </ul>
    )
}

function hasNoValues(frames: DataFrame[]): boolean {
    return frames.every((frame) => frame.fields.every((field) => field.values.length === 0))
}

function ChartData({
    panel,
    viz,
    runQuery,
    states,
}: {
    panel: ContentPanel<ChartConfig>
    viz: VizDefinition
    runQuery: RunQuery
    states?: ChartStates
}): JSX.Element {
    const surroundingTime = useContext(TimeRangeContext)
    const time = panel.config.time ?? surroundingTime
    const targets = chartTargets(panel.config)
    const results = useQueryFrames(
        targets.map(({ query, legend }) => (legend ? { query, time, legend } : { query, time })),
        runQuery
    )
    // Rebuilt only when a result arrives, so the chart keeps its frames, and skips a redraw, on every other render.
    const result = useMemo(
        () => combineTargetResults(chartTargets(panel.config), results, !!panel.config.targets),
        [results, panel.config]
    )
    const parsed = useMemo(
        () => viz.optionsSchema.safeParse(panel.config.viz.options ?? {}),
        [viz.optionsSchema, panel.config.viz.options]
    )
    // The kind of chart wins over the host's defaults, which win over the built-in states.
    const Loading = viz.Loading ?? states?.Loading ?? PanelLoading
    const Empty = viz.Empty ?? states?.Empty ?? DefaultEmpty
    const ErrorState = viz.Error ?? states?.Error ?? DefaultError
    const isEmpty = viz.isEmpty ?? states?.isEmpty ?? hasNoValues

    if (!parsed.success) {
        return <Message>This chart's options are not valid for its chart type.</Message>
    }
    const options = parsed.data
    if (result.status === 'loading') {
        return <Loading options={options} />
    }
    if (result.status === 'error') {
        return <ErrorState message={result.message} options={options} />
    }
    return (
        <div
            className={clsx(
                'flex min-h-0 flex-1 flex-col transition-opacity motion-reduce:transition-none',
                result.refreshing && 'opacity-50'
            )}
            // Always rendered, so the chart inside keeps its instance when a refresh starts or ends.
            aria-busy={result.refreshing || undefined}
        >
            <TargetFailures failures={result.failures} />
            {isEmpty(result.frames) ? (
                <Empty options={options} />
            ) : (
                <viz.Component frames={result.frames} options={options} />
            )}
        </div>
    )
}

export function ChartPanel({
    panel,
    vizTypes,
    runQuery,
    states,
}: {
    panel: ContentPanel<ChartConfig>
    vizTypes: VizDefinition[]
    runQuery?: RunQuery
    states?: ChartStates
}): JSX.Element {
    const viz = vizTypes.find((candidate) => candidate.type === panel.config.viz.type)
    if (!viz) {
        return <Message>This dashboard can't show this chart type.</Message>
    }
    // A host that passes no runner has no data to show, so the tile names its kind of chart instead.
    if (!runQuery) {
        return <Message>{viz.label}</Message>
    }
    return <ChartData panel={panel} viz={viz} runQuery={runQuery} states={states} />
}
