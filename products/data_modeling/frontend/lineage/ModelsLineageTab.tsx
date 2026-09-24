import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonInput, Tooltip } from '@posthog/lemon-ui'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { pluralize } from 'lib/utils/strings'

import { DataModelingNodeType } from '~/types'

import { LineageGraph } from './LineageGraph'
import { lineageNodeUrl } from './lineageNodeUrl'
import { LINEAGE_FILTER_TYPES, modelsLineageLogic } from './modelsLineageLogic'
import { NODE_TYPE_TAG_SETTINGS } from './nodeStyles'
import { NodeTypeLegend } from './NodeTypeLegend'
import { SEARCH_SYNTAX_HELP } from './SearchSyntaxHelp'

const TYPE_OPTIONS = LINEAGE_FILTER_TYPES.map((type) => ({
    key: type,
    label: NODE_TYPE_TAG_SETTINGS[type].label,
}))

export function ModelsLineageTab(): JSX.Element {
    const {
        nodes,
        nodesLoading,
        edgesLoading,
        searchTerm,
        typeFilter,
        legendCollapsed,
        parsedSearch,
        highlightedNodeIds,
        visibleNodes,
        visibleEdges,
        isFiltered,
    } = useValues(modelsLineageLogic)
    const { setSearchTerm, setTypeFilter, toggleLegendCollapsed, resetFilters } = useActions(modelsLineageLogic)
    // A fresh Set on every render would restart the graph's fitView animation each keystroke,
    // so keep the identity stable while the underlying selectors are unchanged.
    const focusNodeIds = useMemo(
        () => (parsedSearch.mode === 'search' ? highlightedNodeIds : new Set(visibleNodes.map((node) => node.id))),
        [parsedSearch.mode, highlightedNodeIds, visibleNodes]
    )

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap gap-2 items-center">
                <LemonInput
                    type="search"
                    size="small"
                    placeholder="Search, or +name for upstream"
                    value={searchTerm}
                    onChange={setSearchTerm}
                    className="w-72"
                    data-attr="models-lineage-search"
                />
                <Tooltip title={SEARCH_SYNTAX_HELP}>
                    <IconInfo className="text-base text-secondary" />
                </Tooltip>
                <div className="w-44">
                    <LemonInputSelect
                        mode="multiple"
                        size="small"
                        placeholder="All types"
                        options={TYPE_OPTIONS}
                        value={typeFilter}
                        onChange={(value) => setTypeFilter(value as DataModelingNodeType[])}
                        displayMode="count"
                        bulkActions="select-and-clear-all"
                        data-attr="models-lineage-type-filter"
                    />
                </div>
                {isFiltered && (
                    <>
                        <span className="text-xs text-secondary">
                            Showing {pluralize(visibleNodes.length, 'model')} of {nodes.length}
                        </span>
                        <LemonButton size="xsmall" onClick={resetFilters} data-attr="models-lineage-reset-filters">
                            Clear filters
                        </LemonButton>
                    </>
                )}
            </div>
            <div className="h-[calc(100vh-20rem)] min-h-[400px] w-full border rounded bg-bg-light overflow-hidden">
                <LineageGraph
                    nodes={visibleNodes}
                    edges={visibleEdges}
                    focusNodeIds={focusNodeIds}
                    variant="canvas"
                    interactive
                    showControls
                    showMinimap
                    minimapPosition="top-right"
                    loading={nodesLoading || edgesLoading}
                    emptyMessage={
                        isFiltered ? 'No models match these filters.' : 'No models yet. Create a view to see it here.'
                    }
                    nodeState={(node) => ({
                        isHighlighted: highlightedNodeIds.has(node.id),
                        isRunning: node.last_run_status === 'Running',
                    })}
                    onNodeClick={(node) => router.actions.push(lineageNodeUrl(node))}
                    panelPosition="bottom-left"
                    panels={<NodeTypeLegend collapsed={legendCollapsed} onToggleCollapse={toggleLegendCollapsed} />}
                />
            </div>
        </div>
    )
}
