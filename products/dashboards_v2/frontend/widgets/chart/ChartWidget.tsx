import clsx from 'clsx'
import { useContext, useMemo } from 'react'

import type { ContentWidget } from '../../dashboard/document/dashboardTypes'
import { FiltersContext } from '../../filters/filtersContext'
import { WidgetLoading } from '../WidgetView'
import { type ChartConfig, chartTargets, hasNoOwnRange } from './chartSpec'
import { type TargetFailure, combineTargetResults } from './data/targetResults'
import { useQueryFrames } from './data/useQueryFrames'
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
    widget,
    viz,
    runQuery,
    states,
}: {
    widget: ContentWidget<ChartConfig>
    viz: VizDefinition
    runQuery: RunQuery
    states?: ChartStates
}): JSX.Element {
    const { time: surroundingTime, filters } = useContext(FiltersContext)
    const time = widget.config.time ?? surroundingTime
    const targets = chartTargets(widget.config)
    // Filters are left out when empty, so a chart's cached result from before any filter existed still matches.
    const results = useQueryFrames(
        targets.map(({ query, legend }) => ({
            query,
            time,
            ...(legend ? { legend } : {}),
            ...(filters.length > 0 ? { filters } : {}),
        })),
        runQuery
    )
    // Rebuilt only when a result arrives, so the chart keeps its frames, and skips a redraw, on every other render.
    const result = useMemo(
        () => combineTargetResults(chartTargets(widget.config), results, !!widget.config.targets),
        [results, widget.config]
    )
    // The kind of chart wins over the host's defaults, which win over the built-in states.
    const Loading = viz.Loading ?? states?.Loading ?? WidgetLoading
    const Empty = viz.Empty ?? states?.Empty ?? DefaultEmpty
    const ErrorState = viz.Error ?? states?.Error ?? DefaultError
    const isEmpty = viz.isEmpty ?? states?.isEmpty ?? hasNoValues

    // The widget's config check already parsed them, and a transforming schema must not run twice.
    const options = widget.config.viz.options ?? {}
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

export function ChartWidget({
    widget,
    vizTypes,
    runQuery,
    states,
}: {
    widget: ContentWidget<ChartConfig>
    vizTypes: VizDefinition[]
    runQuery?: RunQuery
    states?: ChartStates
}): JSX.Element {
    const { time: surroundingTime } = useContext(FiltersContext)
    const viz = vizTypes.find((candidate) => candidate.type === widget.config.viz.type)
    if (!viz) {
        return <Message>This dashboard can't show this chart type.</Message>
    }
    // A host that passes no runner has no data to show, so the tile names its kind of chart instead.
    if (!runQuery) {
        return <Message>{viz.label}</Message>
    }
    if (!(widget.config.time ?? surroundingTime) && chartTargets(widget.config).some(hasNoOwnRange)) {
        return <Message>A PromQL or LogQL chart needs a time range.</Message>
    }
    return <ChartData widget={widget} viz={viz} runQuery={runQuery} states={states} />
}
