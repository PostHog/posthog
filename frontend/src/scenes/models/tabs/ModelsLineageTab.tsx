import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonInput, Tooltip } from '@posthog/lemon-ui'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { urls } from 'scenes/urls'

import { DataModelingNodeType } from '~/types'

import { LineageGraph } from 'products/data_modeling/frontend/lineage/LineageGraph'
import { NODE_TYPE_TAG_SETTINGS } from 'products/data_modeling/frontend/lineage/nodeStyles'
import { NodeTypeLegend } from 'products/data_modeling/frontend/lineage/NodeTypeLegend'

import { LINEAGE_FILTER_TYPES, modelsLineageLogic } from '../modelsLineageLogic'

const SEARCH_HELP = (
    <div className="flex flex-col gap-1">
        <div>Type a name to highlight matching models.</div>
        <div>
            <code>+name</code> keeps the model and everything it depends on.
        </div>
        <div>
            <code>name+</code> keeps the model and everything that depends on it.
        </div>
        <div>
            <code>+name+</code> keeps both sides.
        </div>
    </div>
)

const TYPE_OPTIONS = LINEAGE_FILTER_TYPES.map((type) => ({
    key: type,
    label: NODE_TYPE_TAG_SETTINGS[type].label,
}))

export function ModelsLineageTab(): JSX.Element {
    const {
        nodesLoading,
        edgesLoading,
        searchTerm,
        typeFilter,
        legendCollapsed,
        highlightedNodeIds,
        visibleNodes,
        visibleEdges,
        isFiltered,
    } = useValues(modelsLineageLogic)
    const { setSearchTerm, setTypeFilter, toggleLegendCollapsed, resetFilters } = useActions(modelsLineageLogic)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap gap-2 items-center">
                <LemonInput
                    type="search"
                    size="small"
                    placeholder="Search models, or +name for upstream"
                    value={searchTerm}
                    onChange={setSearchTerm}
                    className="w-72"
                    data-attr="models-lineage-search"
                />
                <Tooltip title={SEARCH_HELP}>
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
                        <span className="text-xs text-secondary">Showing {visibleNodes.length} models</span>
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
                    onNodeClick={(node) => router.actions.push(urls.nodeDetail(node.id))}
                    panelPosition="bottom-left"
                    panels={<NodeTypeLegend collapsed={legendCollapsed} onToggleCollapse={toggleLegendCollapsed} />}
                />
            </div>
        </div>
    )
}
