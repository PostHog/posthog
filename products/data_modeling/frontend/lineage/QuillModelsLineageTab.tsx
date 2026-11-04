import { useActions, useValues } from 'kea'

import { IconArchive, IconInfo, IconSearch } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Text,
} from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { LineageGraph } from './LineageGraph'
import { lineageNodeUrl } from './lineageNodeUrl'
import { modelsLineageLogic } from './modelsLineageLogic'
import { QUILL_LINEAGE_NODE_TYPES } from './QuillLineageNode'
import { QuillLineageSearchResults } from './QuillLineageSearchResults'
import { QuillLineageTypeFilterMenu } from './QuillLineageTypeFilterMenu'
import { QuillNodeTypeLegend } from './QuillNodeTypeLegend'
import { SEARCH_SYNTAX_HELP } from './SearchSyntaxHelp'
import { useLineageSearchInput } from './useLineageSearchInput'

export function QuillModelsLineageTab(): JSX.Element {
    const { searchInputRef, onSearchKeyDown, onSelectResult, onPreviousResult, onNextResult } = useLineageSearchInput()
    const {
        nodes,
        nodesLoading,
        edgesLoading,
        searchTerm,
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
    const { setSearchTerm, toggleLegendCollapsed, nodeDragStopped, resetNodePositions } = useActions(modelsLineageLogic)
    const loading = nodesLoading || edgesLoading

    return (
        <div className="flex flex-col gap-2" data-quill>
            <div className="flex flex-wrap items-center gap-2">
                <InputGroup size="sm" className="w-full @min-[40rem]/main-content:w-72">
                    <InputGroupAddon>
                        <IconSearch />
                    </InputGroupAddon>
                    <InputGroupInput
                        ref={searchInputRef}
                        type="search"
                        placeholder="Search, or +name for upstream"
                        aria-label="Search models"
                        value={searchTerm}
                        onChange={(event) => setSearchTerm(event.target.value)}
                        onKeyDown={onSearchKeyDown}
                        data-attr="models-lineage-search"
                    />
                </InputGroup>
                <Button size="icon" aria-label="Search syntax" tooltip={SEARCH_SYNTAX_HELP}>
                    <IconInfo />
                </Button>
                <QuillLineageTypeFilterMenu />
                {isFiltered && (
                    <Text size="xs" variant="muted" render={<span />} className="tabular-nums">
                        Showing {pluralize(visibleNodes.length, 'model')} of {nodes.length}
                    </Text>
                )}
            </div>
            <div className="relative h-[calc(100vh-20rem)] min-h-100 w-full overflow-hidden rounded-lg border border-border bg-card">
                <span className="sr-only" aria-live="polite">
                    {searchResultAnnouncement}
                </span>
                {showSearchResults && (
                    <QuillLineageSearchResults
                        results={searchResults}
                        selectedResultId={selectedSearchResult?.id}
                        anchorResultId={lineageSearchAnchor?.id}
                        mode={parsedSearchTerm.mode}
                        onSelect={onSelectResult}
                        onPrevious={onPreviousResult}
                        onNext={onNextResult}
                    />
                )}
                {!loading && visibleNodes.length === 0 ? (
                    <Empty className="h-full">
                        <EmptyHeader>
                            <EmptyMedia variant="icon">
                                <IconArchive />
                            </EmptyMedia>
                            <EmptyDescription>
                                {isFiltered
                                    ? 'No models match these filters.'
                                    : 'No models yet. Create a view to see it here.'}
                            </EmptyDescription>
                        </EmptyHeader>
                    </Empty>
                ) : (
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
                        loading={loading}
                        nodeState={(node) => ({
                            isHighlighted: highlightedNodeIds.has(node.id),
                            isSelected: selectedSearchResult?.id === node.id,
                            isRunning: node.last_run_status === 'Running',
                        })}
                        nodeTypes={QUILL_LINEAGE_NODE_TYPES}
                        panels={
                            <QuillNodeTypeLegend collapsed={legendCollapsed} onToggleCollapse={toggleLegendCollapsed} />
                        }
                    />
                )}
            </div>
        </div>
    )
}
