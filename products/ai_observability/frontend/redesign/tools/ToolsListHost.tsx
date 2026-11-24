import { useActions, useValues } from 'kea'
import { useCallback } from 'react'

import { EntityListHost } from '../lists/EntityListHost'
import { withFacets } from '../lists/facetFilters'
import { facetOptionsLogic } from '../lists/facetOptionsLogic'
import { TraceListRow } from '../trace/traceListRows'
import { ToolDetail } from './components/ToolDetail'
import { toolsTableColumns } from './components/toolsTableColumns'
import { TOOLS_LIST_FILTERS, toolsListLogic } from './toolsListLogic'
import { ToolExample, ToolRow } from './toolsQueries'

function toTraceRow(example: ToolExample, tool: string): TraceListRow {
    return { traceId: example.traceId, timestamp: example.timestamp, stepId: example.uuid, label: `Called ${tool}` }
}

export function ToolsListHost(): JSX.Element {
    const { options } = useValues(facetOptionsLogic)
    const { select } = useActions(toolsListLogic)
    const slowThresholdSeconds = options?.slowThresholdSeconds ?? null
    const columns = useCallback(
        (labels: string[]) => toolsTableColumns({ labels, slowThresholdSeconds }),
        [slowThresholdSeconds]
    )

    return (
        <EntityListHost
            logic={toolsListLogic}
            filters={{ ...TOOLS_LIST_FILTERS, listId: 'tools' }}
            columns={columns}
            rowKey={(row: ToolRow) => row.tool}
            searchPlaceholder="Search tools"
            facetControls={['model', 'provider', 'tool', 'errors', 'slow']}
            noun="tool"
            drawerTitle={(tool) => <span className="ph-no-capture font-mono">{tool}</span>}
            traceRows={(tool, detail) => detail.examples.map((example) => toTraceRow(example, tool))}
            renderDetail={({ key, detail, labels, openStepId, openTrace, propertyFilters, setPropertyFilters }) => (
                <ToolDetail
                    detail={detail}
                    labels={labels}
                    activeExampleKey={openStepId}
                    onOpenExample={(example) => openTrace(toTraceRow(example, key))}
                    onSelectTool={select}
                    onFilterModel={(model) =>
                        setPropertyFilters(withFacets(propertyFilters, { models: [model] }, null))
                    }
                />
            )}
            emptyState={{
                title: 'No tool calls in this date range',
                description: 'None of your generations called a tool. Pick a wider date range to check older events.',
            }}
            emptyFilteredTitle="No tools match"
            errorTitle="Could not load tools"
            // pinned: autocapture dashboards select the list and its controls by this value and the suffixes built on it
            data-attr="ai-observability-tools-list"
        />
    )
}
