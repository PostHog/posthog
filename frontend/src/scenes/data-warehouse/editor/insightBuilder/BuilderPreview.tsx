import { useActions, useValues } from 'kea'

import { IconCode, IconGraph } from '@posthog/icons'
import { LemonBanner, LemonSegmentedButton, Link, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { IconTableChart } from 'lib/lemon-ui/icons'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { Table } from '~/queries/nodes/DataVisualization/Components/Table'
import { getChartCapability } from '~/queries/nodes/DataVisualization/insightBuilder/chartCapabilities'
import { baseLimitCap } from '~/queries/nodes/DataVisualization/insightBuilder/compileBuilderQuery'
import { responseSupportsChart } from '~/queries/nodes/DataVisualization/insightBuilder/responseSupportsChart'

import { InternalDataTableVisualization } from '../OutputPane'
import { sqlEditorLogic } from '../sqlEditorLogic'
import { BuilderPreviewView, insightBuilderLogic } from './insightBuilderLogic'

function PreviewEmptyState({
    heading,
    details,
    hint,
}: {
    heading: string
    details: string[]
    hint?: string
}): JSX.Element {
    return (
        <div
            className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center"
            data-attr="sql-builder-preview-empty-state"
        >
            <IconGraph className="mb-1 text-3xl text-tertiary" />
            <span className="text-base font-semibold">{heading}</span>
            {details.map((detail) => (
                <span key={detail} className="max-w-120 text-sm text-secondary">
                    {detail}
                </span>
            ))}
            {hint ? <span className="max-w-120 text-xs text-tertiary">{hint}</span> : null}
        </div>
    )
}

function responseColumnsOf(response: Record<string, any> | null | undefined): string[] | undefined {
    return response && typeof response === 'object' && 'columns' in response && Array.isArray(response.columns)
        ? (response.columns as string[])
        : undefined
}

function responseRowCount(response: Record<string, any> | null | undefined): number | null {
    if (response && typeof response === 'object' && 'results' in response && Array.isArray(response.results)) {
        return response.results.length
    }
    return null
}

/**
 * Freshness strip under the chart: what ran, how long it took, and whether the chart is in sync.
 * The generated SQL itself lives in the preview's SQL view.
 */
function BuilderStatusBar({ tabId, chartInSync }: { tabId: string; chartInSync: boolean }): JSX.Element | null {
    const { runQuery } = useActions(sqlEditorLogic({ tabId }))
    const { baseOutOfSync } = useValues(insightBuilderLogic({ tabId }))
    const { refreshBase } = useActions(insightBuilderLogic({ tabId }))
    const { response, responseLoading, elapsedTime } = useValues(dataNodeLogic)

    const rowCount = responseRowCount(response)

    let status: JSX.Element | null = null
    if (responseLoading) {
        status = <span className="text-secondary">Running query…</span>
    } else if (baseOutOfSync) {
        status = (
            <span className="text-warning">
                Base query changed — <Link onClick={() => refreshBase()}>refresh fields</Link>
            </span>
        )
    } else if (!chartInSync) {
        status = (
            <span className="text-warning">
                Results are from a different query — <Link onClick={() => runQuery()}>run</Link>
            </span>
        )
    } else if (rowCount !== null) {
        status = (
            <span className="text-secondary">
                {rowCount === 1 ? '1 row' : `${rowCount} rows`}
                {elapsedTime ? ` · ${(elapsedTime / 1000).toFixed(elapsedTime < 1000 ? 2 : 1)}s` : ''}
            </span>
        )
    }

    if (!status) {
        return null
    }

    return (
        <div className="shrink-0 border-t" data-attr="sql-builder-status-bar">
            <div className="flex items-center justify-between gap-2 px-2 py-1 text-xs">{status}</div>
        </div>
    )
}

/** The chart itself — the always-visible Visualization column of the builder canvas. */
export function BuilderPreview({ tabId }: { tabId: string }): JSX.Element {
    const { hasAnyField, hydrated, wellProblems, builderDisplay, builderView } = useValues(
        insightBuilderLogic({ tabId })
    )
    const { setBuilderView } = useActions(insightBuilderLogic({ tabId }))
    const { sourceQuery, dataLogicKey, insightLoading } = useValues(sqlEditorLogic({ tabId }))
    const { setSourceQuery } = useActions(sqlEditorLogic({ tabId }))
    const { response, responseError, responseLoading, hasMoreData } = useValues(dataNodeLogic)

    const capability = getChartCapability(builderDisplay)
    const limitCap = sourceQuery.builder?.enabled
        ? baseLimitCap(sourceQuery.builder.baseQuery ?? '', sourceQuery.builder.baseView)
        : null
    // Some backends embed the failure in the response body rather than the error channel
    const queryError =
        responseError ??
        (response && typeof response === 'object' && 'error' in response
            ? (response as { error?: string }).error
            : null)
    const chartInSync = responseLoading || responseSupportsChart(sourceQuery, responseColumnsOf(response))

    let content: JSX.Element
    if (insightLoading || (sourceQuery.builder?.enabled && !hydrated)) {
        // The Visualization tab opens before the insight fetch resolves — show a loader instead
        // of a flash of empty wells that snap into the hydrated chart. Same for a builder node
        // whose hydration hasn't caught up (the canvas chunk, insight fetch, and feature flags
        // all race on a cold reload): "pick fields" would misread loading as an empty canvas.
        content = (
            <div className="flex flex-1 items-center justify-center p-8">
                <Spinner className="text-2xl" />
            </div>
        )
    } else if (!hasAnyField) {
        content = (
            <PreviewEmptyState
                heading="Pick fields to chart"
                details={['Click a field in the Data column, or drag it into a well in Setup.']}
                hint={capability?.requirementHint}
            />
        )
    } else if (wellProblems.length > 0) {
        content = (
            <PreviewEmptyState
                heading={`${capability?.label ?? 'This chart'} needs more fields`}
                details={wellProblems}
                hint={capability?.tip}
            />
        )
    } else if (queryError) {
        content = (
            <div className="flex flex-col gap-2 p-4">
                <LemonBanner type="error">{queryError}</LemonBanner>
                <span className="text-sm text-secondary">
                    If a field no longer exists in the query, remove its highlighted pill or refresh the fields in the
                    Data column.
                </span>
            </div>
        )
    } else if (!chartInSync) {
        // The latest results answer a different query than the chart was built for (e.g. an ad-hoc
        // selection was run) — a blank canvas here would give no clue why nothing renders
        content = (
            <PreviewEmptyState
                heading="Results are from a different query"
                details={['Run the query again to load data for this chart.']}
            />
        )
    } else {
        content = (
            <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-auto">
                {limitCap !== null ? (
                    <LemonBanner type="warning" className="m-2 flex-shrink-0" data-attr="sql-builder-limit-warning">
                        The base query has LIMIT {limitCap}, so this chart aggregates only those {limitCap} rows. Remove
                        the limit from the base query to include all rows.
                    </LemonBanner>
                ) : null}
                {hasMoreData ? (
                    <LemonBanner type="info" className="m-2 flex-shrink-0">
                        Results were truncated at the row limit — aggregates may be incomplete. Narrow the base query or
                        reduce the grouping cardinality.
                    </LemonBanner>
                ) : null}
                {builderView === 'sql' ? (
                    <div className="min-h-0 flex-1 overflow-auto p-2" data-attr="sql-builder-generated-sql">
                        <CodeSnippet language={Language.SQL} wrap thing="generated SQL">
                            {sourceQuery.source.query}
                        </CodeSnippet>
                    </div>
                ) : builderView === 'table' ? (
                    <div className="min-h-0 flex-1 overflow-auto" data-attr="sql-builder-results-table">
                        <Table
                            uniqueKey={dataLogicKey}
                            query={sourceQuery}
                            context={{}}
                            cachedResults={undefined}
                            embedded
                        />
                    </div>
                ) : (
                    <InternalDataTableVisualization
                        uniqueKey={dataLogicKey}
                        query={sourceQuery}
                        setQuery={setSourceQuery}
                        context={{}}
                        cachedResults={undefined}
                        editMode
                        showSettingsPanel={false}
                    />
                )}
            </div>
        )
    }

    const showViewToggle = hasAnyField

    return (
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            {showViewToggle ? (
                <div
                    className="flex shrink-0 items-center justify-end border-b px-2 py-1"
                    data-attr="sql-builder-view-toggle"
                >
                    <LemonSegmentedButton
                        size="xsmall"
                        value={builderView}
                        onChange={(view) => setBuilderView(view as BuilderPreviewView)}
                        options={[
                            { value: 'chart', icon: <IconGraph />, tooltip: 'Chart' },
                            { value: 'table', icon: <IconTableChart />, tooltip: 'Results of the generated SQL' },
                            { value: 'sql', icon: <IconCode />, tooltip: 'Generated SQL' },
                        ]}
                    />
                </div>
            ) : null}
            {content}
            <BuilderStatusBar tabId={tabId} chartInSync={chartInSync} />
        </div>
    )
}
