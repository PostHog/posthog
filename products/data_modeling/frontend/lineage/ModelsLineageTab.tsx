import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonInput, Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { LineageGraph } from './LineageGraph'
import { lineageNodeUrl } from './lineageNodeUrl'
import { LineageSearchResults } from './LineageSearchResults'
import { LineageTypeFilter } from './LineageTypeFilter'
import { modelsLineageLogic } from './modelsLineageLogic'
import { NodeTypeLegend } from './NodeTypeLegend'
import { SEARCH_SYNTAX_HELP } from './SearchSyntaxHelp'

export function ModelsLineageTab(): JSX.Element {
    const searchInputRef = useRef<HTMLInputElement>(null)
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
        graphNodes,
        visibleEdges,
        isFiltered,
        nodePositions,
    } = useValues(modelsLineageLogic)
    const {
        setSearchTerm,
        setDebouncedSearchTerm,
        setTypeFilter,
        moveSearchResult,
        focusSearchResult,
        toggleLegendCollapsed,
        resetFilters,
        nodeDragStopped,
        resetNodePositions,
    } = useActions(modelsLineageLogic)

    const focusSearchInput = (): void => {
        const input = searchInputRef.current
        input?.focus()
        const trimmedSearchTerm = searchTerm.trimEnd()
        if (input && trimmedSearchTerm.length > 1 && trimmedSearchTerm.endsWith('+')) {
            const trailingSelectorPosition = trimmedSearchTerm.length - 1
            input.setSelectionRange(trailingSelectorPosition, trailingSelectorPosition)
        }
    }

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
                    onKeyDown={(event) => {
                        if (
                            showSearchResults &&
                            searchResults.length > 0 &&
                            (event.key === 'ArrowUp' || event.key === 'ArrowDown')
                        ) {
                            event.preventDefault()
                            // Focus stays in the input here, so there is nothing to restore. Calling
                            // focusSearchInput would move the caret away from where the user put it.
                            moveSearchResult(event.key === 'ArrowUp' ? 'previous' : 'next', false)
                        } else if (event.key === 'Enter' && selectedSearchResult) {
                            event.preventDefault()
                            focusSearchResult(selectedSearchResult.id, 'keyboard')
                            focusSearchInput()
                        } else if (event.key === 'Escape' && searchTerm) {
                            event.preventDefault()
                            setSearchTerm('')
                            setDebouncedSearchTerm('')
                        }
                    }}
                    className="w-72"
                    data-attr="models-lineage-search"
                />
                <Tooltip title={SEARCH_SYNTAX_HELP}>
                    <IconInfo className="text-base text-secondary" />
                </Tooltip>
                <LineageTypeFilter value={typeFilter} onChange={setTypeFilter} dataAttr="models-lineage-type-filter" />
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
                        onSelect={(nodeId) => {
                            focusSearchResult(nodeId, 'click')
                            focusSearchInput()
                        }}
                        onPrevious={() => {
                            moveSearchResult('previous', true)
                            focusSearchInput()
                        }}
                        onNext={() => {
                            moveSearchResult('next', true)
                            focusSearchInput()
                        }}
                    />
                )}
                <LineageGraph
                    nodes={graphNodes}
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
