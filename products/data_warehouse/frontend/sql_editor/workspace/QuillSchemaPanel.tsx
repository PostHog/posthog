import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { IconEllipsis, IconPlus, IconSearch, IconX } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuTrigger,
    FilterCheckboxSubMenu,
    FilterClearItem,
    FilterMenuTrigger,
    Input,
    InputGroup,
    InputGroupAddon,
    InputGroupButton,
    InputGroupInput,
    Text,
    Tree,
    TreeItemActions,
    TreeItemIcon,
    TreeItemLabel,
    TreeItemMeta,
    type TreeNode,
} from '@posthog/quill'

import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { TreeNodeDisplayIcon } from 'lib/lemon-ui/LemonTree/LemonTreeUtils'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { PropertyDefinitionFilter } from 'scenes/data-warehouse/editor/sidebar/PropertyDefinitionFilter'
import { queryDatabaseLogic } from 'scenes/data-warehouse/editor/sidebar/queryDatabaseLogic'
import { QuillSchemaItemMenuItems } from 'scenes/data-warehouse/editor/sidebar/QuillSchemaItemMenuItems'
import { getFieldTypeIconComponent } from 'scenes/data-warehouse/editor/sidebar/schemaFieldTypeIcons'
import { formatTraversalChain, getSchemaItemTooltip } from 'scenes/data-warehouse/editor/sidebar/schemaTreeData'
import { useSchemaTreeBehavior } from 'scenes/data-warehouse/editor/sidebar/useSchemaTreeBehavior'
import { getTableKindLabel } from 'scenes/data-warehouse/editor/sidebar/viewKind'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { MaterializationStatusIcon } from 'products/data_modeling/frontend/MaterializationStatusIcon'
import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'
import { TableCertificationIcon } from 'products/data_warehouse/frontend/shared/components/TableCertificationBadge'
import { MATERIALIZATION_STATUS_FILTER_OPTIONS } from 'products/data_warehouse/frontend/shared/filterMaterializedViewsByStatus'

import { QuillConnectionMenu } from './QuillConnectionMenu'

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

const formatRowCount = (count: number | undefined): string | null =>
    count
        ? new Intl.NumberFormat('en', { notation: 'compact', compactDisplay: 'short' }).format(count).toLowerCase()
        : null

/** The quiet prompt to connect a first source, in place of the Lemon sidebar's banner. */
function ConnectSourcesRow(): JSX.Element | null {
    const { hasNonPosthogSources, syncMoreNoticeDismissed, databaseLoading } = useValues(queryDatabaseLogic)
    const { setSyncMoreNoticeDismissed } = useActions(queryDatabaseLogic)
    const { addProductIntent } = useActions(teamLogic)

    if (hasNonPosthogSources || syncMoreNoticeDismissed || databaseLoading) {
        return null
    }

    return (
        <div
            className="flex items-center gap-2 border-t p-2 ps-3"
            // pinned: data-attr read by autocapture dashboards for this prompt
            data-attr="sql-editor-source-empty-state"
        >
            <span className="flex shrink-0 -space-x-1">
                <SourceIcon type="Postgres" size="xsmall" disableTooltip />
                <SourceIcon type="Stripe" size="xsmall" disableTooltip />
                <SourceIcon type="GoogleAds" size="xsmall" disableTooltip />
            </span>
            <Button
                variant="link-foreground"
                size="sm"
                className="min-w-0 truncate"
                onClick={() => {
                    addProductIntent({
                        product_type: ProductKey.DATA_WAREHOUSE,
                        intent_context: ProductIntentContext.SQL_EDITOR_EMPTY_STATE,
                    })
                    router.actions.push(urls.dataWarehouseSourceNew())
                }}
                id="data-warehouse-sql-editor-add-data-source"
            >
                Connect Postgres, Stripe and more
            </Button>
            <Button
                size="icon-xs"
                className="ms-auto"
                aria-label="Dismiss"
                tooltip="Dismiss"
                onClick={() => setSyncMoreNoticeDismissed(true)}
            >
                <IconX />
            </Button>
        </div>
    )
}

/** The schema tab of the editor's side panel: the connection, a search, and the tables to query. */
export function QuillSchemaPanel({ tabId }: { tabId: string }): JSX.Element {
    const {
        searchTerm,
        searchText,
        connectionId,
        expandedItemIds,
        editingDraftId,
        materializationStatusFilters,
        dataWarehouseSavedQueriesLoading,
    } = useValues(queryDatabaseLogic)
    const {
        setSearchTerm,
        clearSearch,
        toggleFolderOpen,
        toggleMaterializationStatusFilter,
        clearMaterializationStatusFilters,
        setPropertyDefinitionSearch,
        renameDraft,
        setEditingDraft,
    } = useActions(queryDatabaseLogic)
    const { treeData, isPreviewableViewItem, previewItem, activateItem, getActionGroups } = useSchemaTreeBehavior()

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
                renderItem={(node, state) => {
                    const { item } = node
                    const record = item.record
                    const isColumn = record?.type === 'column'
                    const FieldIcon = isColumn ? getFieldTypeIconComponent(record?.field?.type) : null
                    const columnType: string | undefined = isColumn ? record?.field?.type : undefined
                    const label = typeof item.displayName === 'string' ? item.displayName : item.name
                    const certification =
                        record?.type === 'table'
                            ? record?.table?.certification
                            : record?.type === 'view'
                              ? record?.certification
                              : undefined
                    const meta = isColumn
                        ? columnType === 'field_traverser'
                            ? (formatTraversalChain(record?.field?.chain) ?? columnType)
                            : columnType
                        : state.hasChildren
                          ? (formatRowCount(record?.row_count) ?? getTableKindLabel(record))
                          : null
                    const groups = node.section && record?.type !== 'views' ? null : getActionGroups(item)

                    if (record?.type === 'draft' && editingDraftId === record?.id) {
                        return (
                            <Input
                                size="sm"
                                autoFocus
                                defaultValue={item.name}
                                aria-label="Draft name"
                                className="h-6"
                                onClick={(event) => event.stopPropagation()}
                                onKeyDown={(event) => {
                                    event.stopPropagation()
                                    if (event.key === 'Enter') {
                                        const name = event.currentTarget.value.trim()
                                        if (name && name !== item.name) {
                                            renameDraft(record.id, name)
                                        }
                                        setEditingDraft('')
                                    } else if (event.key === 'Escape') {
                                        setEditingDraft('')
                                    }
                                }}
                                onBlur={() => setEditingDraft('')}
                            />
                        )
                    }

                    return (
                        <>
                            {!node.section ? (
                                <TreeItemIcon>
                                    {FieldIcon ? (
                                        <FieldIcon />
                                    ) : record?.type === 'view' && record.isSavedQuery ? (
                                        <MaterializationStatusIcon view={record.view} />
                                    ) : (
                                        <TreeNodeDisplayIcon item={item} expandedItemIds={expandedItemIds} />
                                    )}
                                </TreeItemIcon>
                            ) : null}
                            <TreeItemLabel
                                highlight={searchText || undefined}
                                className={isColumn ? 'font-mono' : undefined}
                            >
                                {label}
                            </TreeItemLabel>
                            <TableCertificationIcon certification={certification} />
                            {meta ? <TreeItemMeta>{meta}</TreeItemMeta> : null}
                            {record?.type === 'property-field' ? (
                                <TreeItemActions>
                                    <PropertyDefinitionFilter
                                        propertyDefinitionKey={record.propertyDefinitionKey}
                                        propertyDefinitionSearch={record.propertyDefinitionSearch ?? ''}
                                        propertyDefinitionTarget={record.propertyDefinitionTarget}
                                        setPropertyDefinitionSearch={setPropertyDefinitionSearch}
                                    />
                                </TreeItemActions>
                            ) : record?.type === 'sources' ? (
                                <TreeItemActions>
                                    <Button
                                        size="icon-xs"
                                        aria-label="Add a source"
                                        tooltip="Add a source"
                                        onClick={() => {
                                            posthog.capture('sql-editor-add-source-clicked', {
                                                source_type: null,
                                                location: 'sources_header',
                                            })
                                            newInternalTab(urls.dataWarehouseSourceNew())
                                        }}
                                        data-attr="sql-editor-add-source"
                                    >
                                        <IconPlus />
                                    </Button>
                                </TreeItemActions>
                            ) : groups ? (
                                <TreeItemActions>
                                    <DropdownMenu>
                                        <DropdownMenuTrigger
                                            render={
                                                <Button
                                                    size="icon-xs"
                                                    aria-label={`More for ${item.name}`}
                                                    tooltip="More"
                                                />
                                            }
                                        >
                                            <IconEllipsis />
                                        </DropdownMenuTrigger>
                                        <DropdownMenuContent align="start" side="right">
                                            <QuillSchemaItemMenuItems groups={groups} type="dropdown" />
                                        </DropdownMenuContent>
                                    </DropdownMenu>
                                </TreeItemActions>
                            ) : null}
                        </>
                    )
                }}
            />
            <ConnectSourcesRow />
        </div>
    )
}
