import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { getBIFieldPillLabel } from './biEditorTypes'
import { getBIActiveFilterSummary } from './biFilterSummary'
import { getBIResultSummary, getBIVisualizationSource } from './biQueryResults'
import { biSceneLogic } from './biSceneLogic'

export function BIResultSummary({ tabId }: { tabId: string }): JSX.Element | null {
    const { lastRunQuery, dataNodeKey, worksheet } = useValues(biSceneLogic({ tabId }))
    const { response, responseLoading } = useValues(
        dataNodeLogic({
            key: dataNodeKey,
            query: getBIVisualizationSource(lastRunQuery ?? worksheet),
            autoLoad: !!lastRunQuery,
        })
    )
    const summary = lastRunQuery && !responseLoading ? getBIResultSummary(lastRunQuery, response) : null
    if (!summary || !lastRunQuery) {
        return null
    }
    const dimensions = [...lastRunQuery.config.rows, ...lastRunQuery.config.columns]
    const filters = getBIActiveFilterSummary(lastRunQuery.config)
    const dateRange = lastRunQuery.source.filters?.dateRange ?? lastRunQuery.config.dateRange
    const dateSummary =
        dateRange && dateRange.date_from !== 'all' && (dateRange.date_from || dateRange.date_to)
            ? `${dateRange.date_from || 'Start'} to ${dateRange.date_to || 'now'}`
            : null
    return (
        <div
            className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t px-3 py-2 text-xs text-secondary"
            data-attr="bi-result-summary"
        >
            <Tooltip title="Groups are distinct combinations of the worksheet dimensions. Values count non-empty measure values, including comparison periods. These are aggregated results, not source rows.">
                <span>
                    {summary.groups === null ? 'Group count unavailable' : `${summary.groups.toLocaleString()} groups`}
                    {' · '}
                    {summary.marks.toLocaleString()} values
                </span>
            </Tooltip>
            <span className="min-w-0 break-words">
                {dimensions.length
                    ? `Grouped by ${dimensions.map(getBIFieldPillLabel).join(' × ')}`
                    : 'One group across all matching source rows'}
            </span>
            {(filters.rows || filters.results || dateSummary) && (
                <details className="min-w-0 max-w-full basis-full" data-attr="bi-active-filter-summary">
                    <summary className="cursor-pointer">Applied filters</summary>
                    {dateSummary && <p className="my-1 break-words">Date range: {dateSummary}</p>}
                    {filters.rows && <p className="my-1 break-words">Source rows: {filters.rows}</p>}
                    {filters.results && (
                        <p className="my-1 break-words">After aggregation and calculations: {filters.results}</p>
                    )}
                </details>
            )}
            {(summary.limited || summary.possiblyLimited) && (
                <span className="min-w-0 break-words text-warning" role="status">
                    {summary.limited
                        ? 'Some result groups are omitted.'
                        : 'The result cap was reached. More groups may exist.'}
                    {' Narrow the filters'}
                    {lastRunQuery.config.limit < 50000 ? ' or increase the aggregated row limit' : ''}. Totals,
                    rankings, and comparisons may be incomplete.
                </span>
            )}
        </div>
    )
}
