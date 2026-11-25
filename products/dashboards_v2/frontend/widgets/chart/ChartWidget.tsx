import clsx from 'clsx'
import { useContext, useMemo } from 'react'

import type { ContentWidget } from '../../dashboard/dashboardTypes'
import { TimeRangeContext } from '../timeRangeContext'
import { WidgetLoading } from '../WidgetLoading'
import type { ChartConfig } from './chartSpec'
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
    const surroundingTime = useContext(TimeRangeContext)
    const result = useQueryFrames({ query: widget.config.query, time: widget.config.time ?? surroundingTime }, runQuery)
    const parsed = useMemo(
        () => viz.optionsSchema.safeParse(widget.config.viz.options ?? {}),
        [viz.optionsSchema, widget.config.viz.options]
    )
    // The kind of chart wins over the host's defaults, which win over the built-in states.
    const Loading = viz.Loading ?? states?.Loading ?? WidgetLoading
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
    const viz = vizTypes.find((candidate) => candidate.type === widget.config.viz.type)
    if (!viz) {
        return <Message>This dashboard can't show this chart type.</Message>
    }
    // A host that passes no runner has no data to show, so the tile names its kind of chart instead.
    if (!runQuery) {
        return <Message>{viz.label}</Message>
    }
    return <ChartData widget={widget} viz={viz} runQuery={runQuery} states={states} />
}
