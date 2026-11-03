import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonInput, Tooltip } from '@posthog/lemon-ui'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { pluralize } from 'lib/utils/strings'

import { DataModelingNodeType } from '~/types'

import { LineageGraph } from './LineageGraph'
import { lineageNodeUrl } from './lineageNodeUrl'
import { LineageSearchResults } from './LineageSearchResults'
import { LINEAGE_FILTER_TYPES, modelsLineageLogic } from './modelsLineageLogic'
import { NODE_TYPE_TAG_SETTINGS } from './nodeStyles'
import { NodeTypeLegend } from './NodeTypeLegend'
import { SEARCH_SYNTAX_HELP } from './SearchSyntaxHelp'
import { useLineageSearchInput } from './useLineageSearchInput'

const TYPE_OPTIONS = LINEAGE_FILTER_TYPES.map((type) => ({
    key: type,
    label: NODE_TYPE_TAG_SETTINGS[type].label,
}))

export function ModelsLineageTab(): JSX.Element {
    const { searchInputRef, onSearchKeyDown, onSelectResult, onPreviousResult, onNextResult } = useLineageSearchInput()
    const {
        nodes,
        nodesLoading,
        edgesLoading,
        searchTerm,
        typeFilter,
        legendCollapsed,
        highlightedNodeIds,
        parsedSearchTerm,
        lineageSearchAnchor,
        searchResults,
        showSearchResults,
        selectedSearchResult,
        searchResultAnnouncement,
        searchFocusRequest,
        focusNodeIds,
        visibleNodes,
        visibleEdges,
        isFiltered,
        nodePositions,
    } = useValues(modelsLineageLogic)
    const { setSearchTerm, setTypeFilter, toggleLegendCollapsed, resetFilters, nodeDragStopped, resetNodePositions } =
        useActions(modelsLineageLogic)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap gap-2 items-center">
                <LemonInput
                    type="search"
                    size="small"
                    placeholder="Search, or +name for upstream"
                    aria-label="Search models"
                    inputRef={searchInputRef}
                    value={searchTerm}
                    onChange={setSearchTerm}
                    onKeyDown={onSearchKeyDown}
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
            <div className="relative h-[calc(100vh-20rem)] min-h-[400px] w-full border rounded bg-bg-light overflow-hidden">
                <span className="sr-only" aria-live="polite">
                    {searchResultAnnouncement}
                </span>
                {showSearchResults && (
                    <LineageSearchResults
                        results={searchResults}
                        selectedResultId={selectedSearchResult?.id}
                        anchorResultId={lineageSearchAnchor?.id}
                        mode={parsedSearchTerm.mode}
                        onSelect={onSelectResult}
                        onPrevious={onPreviousResult}
                        onNext={onNextResult}
                    />
                )}
                <LineageGraph
                    nodes={visibleNodes}
                    edges={visibleEdges}
                    focusNodeIds={focusNodeIds}
                    searchFocusRequest={searchFocusRequest}
                    variant="canvas"
                    interactive
                    nodesDraggable
                    nodePositions={nodePositions}
                    nodeOpenUrl={lineageNodeUrl}
                    selectable
                    onNodeDragStop={(node, position) => nodeDragStopped(node.id, position)}
                    onResetNodePositions={resetNodePositions}
                    showControls
                    showMinimap
                    loading={nodesLoading || edgesLoading}
                    emptyMessage={
                        isFiltered ? 'No models match these filters.' : 'No models yet. Create a view to see it here.'
                    }
                    nodeState={(node) => ({
                        isHighlighted: highlightedNodeIds.has(node.id),
                        isSelected: selectedSearchResult?.id === node.id,
                        isRunning: node.last_run_status === 'Running',
                    })}
                    panels={<NodeTypeLegend collapsed={legendCollapsed} onToggleCollapse={toggleLegendCollapsed} />}
                />
            </div>
        </div>
    )
}
