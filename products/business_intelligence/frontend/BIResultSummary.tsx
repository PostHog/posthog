import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { getBIFieldPillLabel } from './biEditorTypes'
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
    return (
        <div
            className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t px-3 py-2 text-xs text-secondary"
            data-attr="bi-result-summary"
        >
            <Tooltip title="Groups are distinct combinations of the worksheet dimensions. Values count non-empty measure values, including comparison periods. These are aggregated results, not source rows.">
                <span>
                    {summary.groups.toLocaleString()} groups · {summary.marks.toLocaleString()} values
                    {summary.limited ? ' (limited)' : ''}
                </span>
            </Tooltip>
            <span className="min-w-0 break-words">
                {dimensions.length
                    ? `Grouped by ${dimensions.map(getBIFieldPillLabel).join(' × ')}`
                    : 'One group across all matching source rows'}
            </span>
        </div>
    )
}
