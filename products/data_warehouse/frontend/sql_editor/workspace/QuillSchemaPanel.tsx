import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconSearch, IconX } from '@posthog/icons'
import {
    DropdownMenu,
    DropdownMenuContent,
    FilterCheckboxSubMenu,
    FilterClearItem,
    FilterMenuTrigger,
    InputGroup,
    InputGroupAddon,
    InputGroupButton,
    InputGroupInput,
    Text,
    Tree,
    type TreeNode,
} from '@posthog/quill'

import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { queryDatabaseLogic } from 'scenes/data-warehouse/editor/sidebar/queryDatabaseLogic'
import { QuillSchemaItemMenuItems } from 'scenes/data-warehouse/editor/sidebar/QuillSchemaItemMenuItems'
import { getSchemaItemTooltip } from 'scenes/data-warehouse/editor/sidebar/schemaTreeData'
import { useSchemaTreeBehavior } from 'scenes/data-warehouse/editor/sidebar/useSchemaTreeBehavior'

import { MATERIALIZATION_STATUS_FILTER_OPTIONS } from 'products/data_warehouse/frontend/shared/filterMaterializedViewsByStatus'

import { QuillConnectionMenu } from './QuillConnectionMenu'
import { QuillConnectSourcesRow } from './QuillConnectSourcesRow'
import { QuillSchemaTreeRow } from './QuillSchemaTreeRow'

interface SchemaTreeNode extends TreeNode {
    item: TreeDataItem
    children?: SchemaTreeNode[]
}

const SCHEMA_ROW_HEIGHT = 28

function toSchemaTreeNodes(items: TreeDataItem[], depth = 0): SchemaTreeNode[] {
    return items
        .filter((item) => item.type !== 'separator')
        .map((item) => ({
            id: item.id,
            textValue: item.name,
            item,
            // The top level holds the tree's sections (Sources, Views, Metrics…), drawn as headings.
            section: depth === 0 && !!item.children,
            disabledReason: item.disabledReason,
            children: item.children ? toSchemaTreeNodes(item.children, depth + 1) : undefined,
        }))
}

/** The schema tab of the editor's side panel: the connection, a search, and the tables to query. */
export function QuillSchemaPanel({ tabId }: { tabId: string }): JSX.Element {
    const {
        searchTerm,
        searchText,
        connectionId,
        expandedItemIds,
        materializationStatusFilters,
        dataWarehouseSavedQueriesLoading,
    } = useValues(queryDatabaseLogic)
    const {
        setSearchTerm,
        clearSearch,
        toggleFolderOpen,
        toggleMaterializationStatusFilter,
        clearMaterializationStatusFilters,
    } = useActions(queryDatabaseLogic)
    const { treeData, isPreviewableViewItem, previewItem, activateItem, getActionGroups, addSource } =
        useSchemaTreeBehavior()

    const nodes = useMemo(() => toSchemaTreeNodes(treeData), [treeData])

    const filtersActive = materializationStatusFilters.length > 0

    return (
        <div className="flex h-full min-h-0 flex-col">
            <div className="flex flex-col gap-1.5 p-2">
                <QuillConnectionMenu tabId={tabId} className="w-full" />
                <div className="flex items-center gap-1">
                    <InputGroup size="sm" className="flex-1">
                        <InputGroupAddon>
                            <IconSearch />
                        </InputGroupAddon>
                        <InputGroupInput
                            type="search"
                            placeholder="Search tables and columns"
                            aria-label="Search tables and columns"
                            value={searchTerm}
                            onChange={(event) => setSearchTerm(event.target.value)}
                            data-attr="sql-editor-schema-search"
                        />
                        {searchTerm ? (
                            <InputGroupAddon align="inline-end">
                                <InputGroupButton
                                    size="icon-xs"
                                    aria-label="Clear search"
                                    onClick={() => clearSearch()}
                                    data-attr="tree-search-autocomplete-clear-button"
                                >
                                    <IconX />
                                </InputGroupButton>
                            </InputGroupAddon>
                        ) : null}
                    </InputGroup>
                    {!connectionId ? (
                        <DropdownMenu>
                            <FilterMenuTrigger active={filtersActive} dataAttr="sql-editor-table-filters-menu" />
                            <DropdownMenuContent align="end" className="min-w-56">
                                <FilterCheckboxSubMenu
                                    label="Materialization"
                                    allLabel="Any status"
                                    pluralNoun="statuses"
                                    options={MATERIALIZATION_STATUS_FILTER_OPTIONS.map((status) => ({
                                        value: status,
                                        label: status,
                                    }))}
                                    selected={materializationStatusFilters}
                                    onChange={(selected) => {
                                        // The logic toggles one status at a time, so apply the difference.
                                        for (const status of MATERIALIZATION_STATUS_FILTER_OPTIONS) {
                                            if (
                                                selected.includes(status) !==
                                                materializationStatusFilters.includes(status)
                                            ) {
                                                toggleMaterializationStatusFilter(status)
                                            }
                                        }
                                    }}
                                    dataAttr="sql-editor-materialization-status-filter"
                                />
                                <FilterClearItem
                                    active={filtersActive}
                                    onClear={() => clearMaterializationStatusFilters()}
                                    dataAttr="sql-editor-clear-materialization-filters"
                                />
                            </DropdownMenuContent>
                        </DropdownMenu>
                    ) : null}
                </div>
            </div>
            <Tree<SchemaTreeNode>
                aria-label="Schema"
                className="min-h-0 flex-1 px-1.5"
                items={nodes}
                virtualized
                rowHeight={SCHEMA_ROW_HEIGHT}
                expandedIds={expandedItemIds}
                onExpandedIdsChange={(_, { id, expanded }) => toggleFolderOpen(id, !expanded)}
                onAction={(node) => {
                    if (isPreviewableViewItem(node.item)) {
                        previewItem(node.item)
                        return
                    }
                    activateItem(node.item)
                    node.item.onClick?.()
                }}
                getItemProps={(node) => {
                    const tooltip = getSchemaItemTooltip(node.item)
                    return {
                        title: tooltip ? [tooltip.title, tooltip.description].filter(Boolean).join('\n') : undefined,
                        'data-attr': `sql-editor-schema-row-${node.item.record?.type ?? 'item'}`,
                    }
                }}
                renderContextMenu={(node) => {
                    const groups = getActionGroups(node.item)
                    return groups ? <QuillSchemaItemMenuItems groups={groups} type="context" /> : null
                }}
                empty={
                    <Text size="xs" className="m-0 p-3 text-muted-foreground">
                        {filtersActive && !dataWarehouseSavedQueriesLoading
                            ? 'No materialized views match your filters.'
                            : searchText
                              ? `No tables or columns match "${searchText}".`
                              : 'No tables yet.'}
                    </Text>
                }
                renderItem={(node, state) => (
                    <QuillSchemaTreeRow
                        item={node.item}
                        section={!!node.section}
                        hasChildren={state.hasChildren}
                        actionGroups={
                            node.section && node.item.record?.type !== 'views' ? null : getActionGroups(node.item)
                        }
                        onAddSource={addSource}
                    />
                )}
            />
            <QuillConnectSourcesRow />
        </div>
    )
}
