import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { Fragment } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonInput, Tooltip } from '@posthog/lemon-ui'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { DataModelingNodeType } from '~/types'

import { LineageGraph } from 'products/data_modeling/frontend/lineage/LineageGraph'
import { NODE_TYPE_TAG_SETTINGS } from 'products/data_modeling/frontend/lineage/nodeStyles'
import { NodeTypeLegend } from 'products/data_modeling/frontend/lineage/NodeTypeLegend'

import { LINEAGE_FILTER_TYPES, modelsLineageLogic } from '../modelsLineageLogic'

const SEARCH_SYNTAX: { syntax: string; meaning: string }[] = [
    { syntax: '+name', meaning: 'The model and everything it depends on' },
    { syntax: 'name+', meaning: 'The model and everything that depends on it' },
    { syntax: '+name+', meaning: 'Both sides' },
]

const SEARCH_HELP = (
    <div className="flex flex-col gap-2 max-w-72">
        <p className="m-0">Type a name to highlight matching models.</p>
        <p className="m-0">Add a plus to hide everything else:</p>
        <div className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 items-baseline">
            {SEARCH_SYNTAX.map(({ syntax, meaning }) => (
                <Fragment key={syntax}>
                    <code className="rounded border border-current/40 px-1 text-xs whitespace-nowrap">{syntax}</code>
                    <span>{meaning}</span>
                </Fragment>
            ))}
        </div>
    </div>
)

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
                    placeholder="Search, or +name for upstream"
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
