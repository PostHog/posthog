import clsx from 'clsx'
import { Suspense, useContext, useMemo } from 'react'

import { FiltersContext } from '../../filters/filtersContext'
import type { DataFrame, RunQuery } from '../../query/queryTypes'
import { useQueryFrames } from '../../query/useQueryFrames'
import { type ContentPanel } from '../core/panelSchema'
import { PanelLoading, PanelMessage } from '../core/PanelView'
import { type ChartConfig, chartTargets, hasNoOwnRange } from './chartSpec'
import { type TargetFailure, combineTargetResults } from './data/targetResults'
import type { ChartStates, VizDefinition } from './vizTypes'

function DefaultEmpty(): JSX.Element {
    return (
        <PanelMessage
            problem="empty"
            title="There are no results for this query"
            description="Try changing the date range or the filters."
        />
    )
}

function DefaultError({ message }: { message: string }): JSX.Element {
    return <PanelMessage problem="failedQuery" title="Couldn't run this query" description={message} />
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
    const { time: surroundingTime, filters } = useContext(FiltersContext)
    const time = panel.config.time ?? surroundingTime
    const targets = chartTargets(panel.config)
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
        () => combineTargetResults(chartTargets(panel.config), results, !!panel.config.targets),
        [results, panel.config]
    )
    // The kind of chart wins over the host's defaults, which win over the built-in states.
    const Loading = viz.Loading ?? states?.Loading ?? PanelLoading
    const Empty = viz.Empty ?? states?.Empty ?? DefaultEmpty
    const ErrorState = viz.Error ?? states?.Error ?? DefaultError
    const isEmpty = viz.isEmpty ?? states?.isEmpty ?? hasNoValues

    // The panel's config check already parsed them, and a transforming schema must not run twice.
    const options = panel.config.viz.options ?? {}
    if (result.status === 'loading') {
        return <Loading options={options} />
    }
    if (result.status === 'error') {
        return <ErrorState message={result.message} options={options} />
    }
    return (
        <div
            className={clsx(
                'relative flex min-h-0 w-full flex-1 flex-col transition-opacity motion-reduce:transition-none',
                result.refreshing && 'opacity-50'
            )}
            // Always rendered, so the chart inside keeps its instance when a refresh starts or ends.
            aria-busy={result.refreshing || undefined}
        >
            <TargetFailures failures={result.failures} />
            {isEmpty(result.frames) ? (
                <Empty options={options} />
            ) : (
                <Suspense fallback={<Loading options={options} />}>
                    <viz.Component frames={result.frames} options={options} />
                </Suspense>
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
    const { time: surroundingTime } = useContext(FiltersContext)
    const viz = vizTypes.find((candidate) => candidate.type === panel.config.viz.type)
    if (!viz) {
        return (
            <PanelMessage
                problem="unknownType"
                title="This chart type isn't available"
                description="This dashboard can't draw charts of this type."
            />
        )
    }
    // A host that passes no runner has no data to show, so the tile names its kind of chart instead.
    if (!runQuery) {
        return <PanelMessage title={viz.label} />
    }
    if (!(panel.config.time ?? surroundingTime) && chartTargets(panel.config).some(hasNoOwnRange)) {
        return (
            <PanelMessage
                problem="invalidSettings"
                title="This chart needs a time range"
                description="PromQL and LogQL queries don't carry one, so set one on the chart or the dashboard."
            />
        )
    }
    return <ChartData panel={panel} viz={viz} runQuery={runQuery} states={states} />
}
