import { useValues } from 'kea'
import { useMemo } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { insightLogic } from 'scenes/insights/insightLogic'

import { Query } from '~/queries/Query/Query'
import { DataVisualizationNode, Node, SavedInsightNode } from '~/queries/schema/schema-general'
import { isDataVisualizationNode, isInsightVizNode, isSavedInsightNode } from '~/queries/utils'
import { ChartDisplayType, InsightLogicProps } from '~/types'

import { ChartContent } from './artefactTypes'

/**
 * Strip the chrome a query node carries for the insight scene (filter bar, header, results table)
 * so the report shows the chart alone. A scout writes the query against the insight schema, so it
 * can arrive with any of these turned on. Mirrors what `NotebookNodeQuery` does for the same reason.
 */
function asEmbeddedChart(query: Record<string, any>): Node {
    const node = { ...query, full: false } as any
    if (isInsightVizNode(node) || isSavedInsightNode(node)) {
        node.showFilters = false
        node.showHeader = false
        node.showTable = false
        node.showCorrelationTable = false
        node.embedded = true
    }
    return node as Node
}

/** A SQL node draws a table unless it was given a graphical display, and only a graph needs a box. */
function isGraphicalSqlNode(query: Node): boolean {
    if (!isDataVisualizationNode(query)) {
        return false
    }
    const { display } = query as DataVisualizationNode
    return !!display && display !== ChartDisplayType.ActionsTable
}

/**
 * A chart pointed at a saved insight, refused when that insight does not resolve.
 *
 * `insightDataLogic` falls back to a default trends query for an insight it could not load, so
 * handing a dangling reference straight to `Query` would draw unrelated project data under the
 * scout's title and caption, which a reader has no way to tell is not the scout's evidence.
 */
function SavedInsightChartBody({ query, uniqueKey }: { query: SavedInsightNode; uniqueKey: string }): JSX.Element {
    const insightProps: InsightLogicProps = { dashboardItemId: query.shortId }
    const { insight, insightLoading } = useValues(insightLogic(insightProps))

    if (insightLoading) {
        return <Spinner className="self-center m-auto" />
    }
    // A load failure leaves the empty insight the logic starts from, so an absent query covers both
    // a deleted insight and one this reader cannot see.
    if (!insight?.query) {
        return <p className="m-auto text-xs text-tertiary">Can't load the insight behind this chart.</p>
    }
    return <Query query={query} uniqueKey={uniqueKey} readOnly embedded />
}

/**
 * One chart attached to a report, drawn from the query its author supplied.
 *
 * The query is persisted unparsed (the backend checks only `kind` and a size bound), so `Query` can
 * be handed something it cannot draw. That degrades to `Query`'s own error boundary rather than
 * taking the report down with it.
 */
export function ReportChart({ chart }: { chart: ChartContent }): JSX.Element | null {
    const query = useMemo(() => (chart.query ? asEmbeddedChart(chart.query) : null), [chart.query])

    if (!query) {
        return null
    }

    // A graph fills whatever box it's given and collapses without one. A data table sizes itself to
    // its rows, so forcing the same height on it would just pad short results with blank space.
    const needsFixedHeight = isInsightVizNode(query) || isSavedInsightNode(query) || isGraphicalSqlNode(query)
    // The SQLEditor prefix opts into container-governed chart sizing
    // (dataVisualizationLogic.presetChartHeight). Without it a graphical SQL chart renders at 60vh
    // and swallows the report, which is why NotebookNodeSQLV2 prefixes its key the same way.
    const uniqueKey = `SQLEditor-report-chart-${chart.chart_id}`

    return (
        <div
            className="flex flex-col gap-2 rounded border border-primary bg-surface-primary p-3"
            data-attr="report-chart"
        >
            <h4 className="m-0 text-sm font-semibold text-primary">{chart.title}</h4>
            <div className={needsFixedHeight ? 'h-[18rem] flex flex-col' : 'flex flex-col'}>
                {isSavedInsightNode(query) ? (
                    <SavedInsightChartBody query={query} uniqueKey={uniqueKey} />
                ) : (
                    <Query query={query} uniqueKey={uniqueKey} readOnly embedded />
                )}
            </div>
            {chart.caption ? <p className="m-0 text-xs text-tertiary">{chart.caption}</p> : null}
        </div>
    )
}
