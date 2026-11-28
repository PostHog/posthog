import { DragEndEvent, DragOverEvent, DragStartEvent } from '@dnd-kit/core'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useRef } from 'react'

import { IconChevronRight, IconExternal, IconPlusSmall } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { LemonTree, LemonTreeRef, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { TreeNodeDisplayIcon } from 'lib/lemon-ui/LemonTree/LemonTreeUtils'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuSub,
    ContextMenuSubContent,
    ContextMenuSubTrigger,
} from 'lib/ui/ContextMenu/ContextMenu'
import {
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { cn } from 'lib/utils/css-classes'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { PropertyDefinitionEditModal } from 'scenes/data-management/properties/PropertyDefinitionEditModal'
import { urls } from 'scenes/urls'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'
import { DatabaseSerializedFieldType } from '~/queries/schema/schema-general'

import { MaterializationStatusIcon } from 'products/data_modeling/frontend/MaterializationStatusIcon'
import { RenameViewModal } from 'products/data_warehouse/frontend/shared/components/RenameViewModal'
import { TableCertificationIcon } from 'products/data_warehouse/frontend/shared/components/TableCertificationBadge'
import { expressionModalLogic } from 'products/data_warehouse/frontend/shared/logics/expressionModalLogic'

import { dataWarehouseViewsLogic } from '../../saved_queries/dataWarehouseViewsLogic'
import { renderTableCount } from '../editorSceneLogic'
import { PropertyDefinitionFilter } from './PropertyDefinitionFilter'
import { queryDatabaseLogic } from './queryDatabaseLogic'
import { getFieldTypeIconClassName, getFieldTypeIconComponent } from './schemaFieldTypeIcons'
import { SchemaItemAction } from './schemaItemActions'
import { formatTraversalChain, getSchemaItemTooltip } from './schemaTreeData'
import { TreeRowOverflowText } from './TreeRowOverflowText'
import { useSchemaTreeBehavior } from './useSchemaTreeBehavior'
import { getTableKindLabel } from './viewKind'

export const QueryDatabase = ({
    virtualizationScrollContainerRef,
    extraTreeSections,
}: {
    virtualizationScrollContainerRef?: React.RefObject<HTMLDivElement | null>
    /**
     * Extra top-level sections to render above the database tree, owned by the embedding surface
     * (notebooks lists the dataframes its kernel holds). Rendered as-is: whatever builds them owns
     * their icons, children, and search filtering. Default empty, so surfaces that pass nothing are
     * unaffected.
     */
    extraTreeSections?: TreeDataItem[]
}): JSX.Element => {
    const {
        searchText,
        editingDraftId,
        expandedItemIds,
        connectionId,
        activeDraggedViewId,
        highlightedDropFolderId,
        highlightViewsSectionDrop,
        editingPropertyDefinition,
        materializationStatusFilters,
        dataWarehouseSavedQueriesLoading,
        renameView,
    } = useValues(queryDatabaseLogic)
    const {
        setExpandedFolders,
        toggleFolderOpen,
        setTreeRef,
        setExpandedSearchFolders,
        startDraggingView,
        updateDraggedViewDropTarget,
        clearDraggedViewState,
        moveDraggedViewToDropTarget,
        setEditingDraft,
        renameDraft,
        setPropertyDefinitionSearch,
        closePropertyDefinitionEditor,
        updatePropertyDefinition,
        closeRenameView,
        setRenameViewName,
        submitRenameView,
    } = useActions(queryDatabaseLogic)
    const { dataWarehouseSavedQueriesLoaded, dataWarehouseSavedQueryDownstreamReferences } =
        useValues(dataWarehouseViewsLogic)
    const { expressionsByFieldName } = useValues(expressionModalLogic)
    const { treeData, renameSavedViewEnabled, isPreviewableViewItem, previewItem, activateItem, getActionGroups } =
        useSchemaTreeBehavior(extraTreeSections)

    const getFieldTypeIcon = (fieldType?: DatabaseSerializedFieldType): JSX.Element | null => {
        const Icon = getFieldTypeIconComponent(fieldType)
        return Icon && fieldType ? <Icon className={getFieldTypeIconClassName(fieldType)} /> : null
    }

    const treeRef = useRef<LemonTreeRef>(null)
    useEffect(() => {
        setTreeRef(treeRef)
    }, [treeRef, setTreeRef])

    // Right-clicking a row opens the same actions as its side action menu. Radix context menus need
    // ContextMenu items, so the component set is chosen by `type`.
    const renderItemActions = (item: TreeDataItem, type: 'context' | 'dropdown'): React.ReactNode | undefined => {
        // Null, unlike undefined, keeps the row's side action button: the property filter and the
        // add-source button render through it.
        if (item.record?.type === 'property-field' || item.record?.type === 'sources') {
            return null
        }

        const groups = getActionGroups(item)
        if (!groups) {
            return undefined
        }

        const MenuGroup = type === 'context' ? ContextMenuGroup : DropdownMenuGroup
        const MenuItem = type === 'context' ? ContextMenuItem : DropdownMenuItem
        const MenuSub = type === 'context' ? ContextMenuSub : DropdownMenuSub
        const MenuSubTrigger = type === 'context' ? ContextMenuSubTrigger : DropdownMenuSubTrigger
        const MenuSubContent = type === 'context' ? ContextMenuSubContent : DropdownMenuSubContent

        const renderAction = (action: SchemaItemAction): JSX.Element => {
            switch (action.kind) {
                case 'item':
                    return (
                        <MenuItem
                            key={action.key}
                            asChild
                            onClick={(e) => {
                                e.stopPropagation()
                                action.onSelect()
                            }}
                        >
                            <ButtonPrimitive
                                menuItem
                                className={action.destructive ? 'text-danger' : undefined}
                                disabledReasons={action.disabledReason ? { [action.disabledReason]: true } : undefined}
                                data-attr={action.dataAttr}
                            >
                                {action.label}
                            </ButtonPrimitive>
                        </MenuItem>
                    )
                case 'link':
                    return (
                        <MenuItem key={action.key} asChild>
                            <Link
                                to={action.href}
                                target={action.newTab ? '_blank' : undefined}
                                buttonProps={{ menuItem: true }}
                                onClick={(e) => {
                                    e.stopPropagation()
                                    action.onSelect?.()
                                }}
                                data-attr={action.dataAttr}
                            >
                                {action.label}
                            </Link>
                        </MenuItem>
                    )
                case 'open':
                    return (
                        <div key={action.key} className="flex gap-px">
                            {action.openInPlace ? (
                                <>
                                    <MenuItem asChild>
                                        <Link
                                            to={action.href}
                                            onClick={(e) => e.stopPropagation()}
                                            disabledReason={action.disabledReason}
                                            buttonProps={{
                                                menuItem: true,
                                                className: 'flex-1 rounded-r-none',
                                            }}
                                        >
                                            {action.label}
                                        </Link>
                                    </MenuItem>
                                    <MenuItem asChild>
                                        <Link
                                            to={action.href}
                                            target="_blank"
                                            targetBlankIcon={false}
                                            onClick={(e) => e.stopPropagation()}
                                            disabledReason={action.disabledReason}
                                            tooltip={action.label}
                                            buttonProps={{
                                                menuItem: true,
                                                iconOnly: true,
                                                className: 'px-2 rounded-l-none',
                                            }}
                                        >
                                            <IconExternal />
                                        </Link>
                                    </MenuItem>
                                </>
                            ) : (
                                <MenuItem
                                    asChild
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        newInternalTab(action.href)
                                    }}
                                >
                                    <ButtonPrimitive menuItem>{action.label}</ButtonPrimitive>
                                </MenuItem>
                            )}
                        </div>
                    )
                case 'submenu':
                    return (
                        <MenuSub key={action.key}>
                            <MenuSubTrigger asChild>
                                <ButtonPrimitive menuItem>
                                    {action.label}
                                    <IconChevronRight className="ml-auto size-3" />
                                </ButtonPrimitive>
                            </MenuSubTrigger>
                            <MenuSubContent>{action.items.map(renderAction)}</MenuSubContent>
                        </MenuSub>
                    )
            }
        }

        // lib/ui menus have no separators here, so every group renders in one menu group.
        return <MenuGroup>{groups.flat().map(renderAction)}</MenuGroup>
    }

    const tree = (
        <LemonTree
            ref={treeRef}
            data={treeData}
            enableDragAndDrop={!searchText}
            isItemDraggable={(item) => !searchText && item.record?.type === 'view' && item.record?.isSavedQuery}
            isItemDroppable={(item) =>
                !searchText &&
                ((item.record?.type === 'folder' && item.record?.folderType === 'view-folder') ||
                    item.record?.type === 'views')
            }
            onDragStart={(dragEvent: DragStartEvent) => {
                startDraggingView(String(dragEvent.active.id))
            }}
            onDragOver={(dragEvent: DragOverEvent) => {
                updateDraggedViewDropTarget(dragEvent.over?.id ? String(dragEvent.over.id) : null)
            }}
            onDragCancel={clearDraggedViewState}
            onDragEnd={(dragEvent: DragEndEvent) => {
                moveDraggedViewToDropTarget(
                    String(dragEvent.active.id),
                    dragEvent.over?.id ? String(dragEvent.over.id) : null
                )
            }}
            expandedItemIds={expandedItemIds}
            onSetExpandedItemIds={
                searchText ? setExpandedSearchFolders : (folderIds) => setExpandedFolders(folderIds, connectionId)
            }
            onFolderClick={(folder, isExpanded) => {
                if (folder) {
                    toggleFolderOpen(folder.id, isExpanded)
                }
            }}
            isItemEditing={(item) => {
                return editingDraftId === item.record?.id
            }}
            onItemNameChange={(item, name) => {
                if (item.name !== name) {
                    renameDraft(item.record?.id, name)
                }
                setEditingDraft('')
            }}
            onItemClick={(item) => {
                if (item) {
                    activateItem(item)
                }
            }}
            renderItem={(item) => {
                // Check if item has search matches for highlighting
                const matches = item.record?.searchMatches
                const hasMatches = matches && matches.length > 0
                const isColumn = item.record?.type === 'column'
                const columnType = isColumn ? item.record?.field?.type : null
                const savedExpression =
                    isColumn && item.record?.table && item.record?.field
                        ? expressionsByFieldName[`${item.record.table}.${item.record.field.name}`]
                        : null
                const tableKindLabel = !isColumn && item.children?.length ? getTableKindLabel(item.record) : null
                const certification =
                    item.record?.type === 'table'
                        ? item.record?.table?.certification
                        : item.record?.type === 'view'
                          ? item.record?.certification
                          : undefined
                const itemLabel = typeof item.displayName === 'string' ? item.displayName : item.name
                const isHighlightedFolderDropTarget =
                    item.record?.type === 'folder' &&
                    item.record?.folderType === 'view-folder' &&
                    item.record.folder.id === highlightedDropFolderId
                const isHighlightedViewsDropTarget = item.record?.type === 'views' && highlightViewsSectionDrop
                const showDropTargetBadge =
                    activeDraggedViewId &&
                    (isHighlightedFolderDropTarget || isHighlightedViewsDropTarget) &&
                    activeDraggedViewId !== item.id

                return (
                    <span
                        className="truncate"
                        onDoubleClick={(e) => {
                            if (!isPreviewableViewItem(item)) {
                                return
                            }
                            e.stopPropagation()
                            previewItem(item)
                        }}
                    >
                        <div className="@container/database-tree-row flex flex-row gap-1 justify-between">
                            <div className="flex min-w-0 items-center gap-2">
                                <span className="flex min-w-0 items-center gap-1">
                                    {item.record?.type === 'view' && item.record.isSavedQuery ? (
                                        <MaterializationStatusIcon view={item.record.view} />
                                    ) : null}
                                    <TreeRowOverflowText
                                        className={cn(
                                            !(hasMatches && searchText) &&
                                                ([
                                                    'managed-views',
                                                    'views',
                                                    'sources',
                                                    'drafts',
                                                    'unsaved-folder',
                                                ].includes(item.record?.type) ||
                                                    (item.record?.type === 'folder' &&
                                                        item.record?.folderType === 'view-folder')) &&
                                                'font-semibold',
                                            isColumn && 'font-mono text-xs'
                                        )}
                                    >
                                        {hasMatches && searchText ? (
                                            <SearchHighlightMultiple string={itemLabel} substring={searchText} />
                                        ) : (
                                            (item.displayName ?? item.name)
                                        )}
                                    </TreeRowOverflowText>
                                </span>
                                <TableCertificationIcon certification={certification} />
                                {isColumn && columnType && savedExpression ? (
                                    <Tooltip title={<code className="text-xs">{savedExpression.expression}</code>}>
                                        <span className="shrink rounded px-1.5 py-0.5 text-xs text-muted-alt">
                                            {columnType === 'expression' ? 'expression' : `${columnType} expression`}
                                        </span>
                                    </Tooltip>
                                ) : isColumn && columnType ? (
                                    <span className="shrink rounded px-1.5 py-0.5 text-xs text-muted-alt">
                                        {columnType === 'field_traverser' && item?.record?.field.chain
                                            ? formatTraversalChain(item.record.field.chain)
                                            : columnType}
                                    </span>
                                ) : tableKindLabel ? (
                                    // Below 14rem the badge squeezes a long name to a few characters, so it hides.
                                    // A row at DATABASE_TREE_DEFAULT_WIDTH is wider than 14rem and keeps the badge.
                                    <span className="shrink rounded px-1.5 py-0.5 text-xs text-muted-alt @max-[14rem]/database-tree-row:hidden">
                                        {tableKindLabel}
                                    </span>
                                ) : showDropTargetBadge ? (
                                    <span className="shrink rounded px-1.5 py-0.5 text-xs bg-accent-highlight-secondary text-accent">
                                        Drop here
                                    </span>
                                ) : null}
                            </div>
                            {renderTableCount(item.record?.row_count)}
                        </div>
                    </span>
                )
            }}
            itemSideAction={(item) => renderItemActions(item, 'dropdown')}
            itemContextMenu={(item) => renderItemActions(item, 'context')}
            itemSideActionButton={(item) => {
                if (item.record?.type === 'property-field') {
                    return (
                        <PropertyDefinitionFilter
                            propertyDefinitionKey={item.record.propertyDefinitionKey}
                            propertyDefinitionSearch={item.record.propertyDefinitionSearch ?? ''}
                            propertyDefinitionTarget={item.record.propertyDefinitionTarget}
                            setPropertyDefinitionSearch={setPropertyDefinitionSearch}
                        />
                    )
                }

                if (item.record?.type === 'sources') {
                    return (
                        <ButtonPrimitive
                            iconOnly
                            isSideActionRight
                            className="z-2"
                            onClick={(e) => {
                                e.stopPropagation()
                                posthog.capture('sql-editor-add-source-clicked', {
                                    source_type: null,
                                    location: 'sources_header',
                                })
                                newInternalTab(urls.dataWarehouseSourceNew())
                            }}
                            data-attr="sql-editor-add-source"
                        >
                            <IconPlusSmall className="text-tertiary" />
                        </ButtonPrimitive>
                    )
                }

                // External source folders fall through to the default ellipsis trigger, which opens
                // the actions menu (edit source / add new source of this type) defined in itemSideAction
            }}
            renderItemTooltip={(item) => {
                // Show the description, or the traversal chain of a joined column, which the row does not show
                const tooltip = getSchemaItemTooltip(item)
                if (!tooltip) {
                    return undefined
                }
                if (!tooltip.description) {
                    return tooltip.title
                }
                return (
                    <div className="flex flex-col gap-1">
                        <span className="font-semibold">{tooltip.title}</span>
                        <span>{tooltip.description}</span>
                    </div>
                )
            }}
            renderItemIcon={(item) => {
                if (item.record?.type === 'property-field') {
                    return (
                        <TreeNodeDisplayIcon
                            item={{ ...item, record: { ...item.record, type: 'table' } }}
                            expandedItemIds={expandedItemIds}
                        />
                    )
                }
                if (item.record?.type === 'column') {
                    const icon = getFieldTypeIcon(item.record.field?.type)
                    const savedExpression =
                        item.record?.table && item.record?.field
                            ? expressionsByFieldName[`${item.record.table}.${item.record.field.name}`]
                            : null
                    if (savedExpression) {
                        return (
                            <span className="relative inline-flex">
                                {icon}
                                <span
                                    className="absolute -top-0.5 -right-0.5 size-1.5 rounded-full bg-accent"
                                    aria-hidden="true"
                                />
                            </span>
                        )
                    }
                    return icon
                }
                return <TreeNodeDisplayIcon item={item} expandedItemIds={expandedItemIds} />
            }}
            virtualized
            virtualizationScrollContainerRef={virtualizationScrollContainerRef}
        />
    )

    return (
        <>
            {!connectionId &&
                materializationStatusFilters.length > 0 &&
                dataWarehouseSavedQueriesLoaded &&
                !dataWarehouseSavedQueriesLoading &&
                treeData.length === 0 && (
                    <p className="px-3 py-2 text-muted text-sm">No materialized views match your filters.</p>
                )}
            {tree}
            {editingPropertyDefinition ? (
                <PropertyDefinitionEditModal
                    propertyDefinition={editingPropertyDefinition}
                    onClose={closePropertyDefinitionEditor}
                    onSave={updatePropertyDefinition}
                />
            ) : null}
            {renameSavedViewEnabled && renameView ? (
                <RenameViewModal
                    key={renameView.id}
                    viewName={renameView.originalName}
                    name={renameView.name}
                    nameError={renameView.nameError}
                    submitError={renameView.submitError}
                    isSaving={renameView.isSaving}
                    references={dataWarehouseSavedQueryDownstreamReferences[renameView.id]?.references ?? []}
                    referencesLoading={dataWarehouseSavedQueryDownstreamReferences[renameView.id]?.loading ?? true}
                    referencesError={dataWarehouseSavedQueryDownstreamReferences[renameView.id]?.error ?? false}
                    onNameChange={setRenameViewName}
                    onClose={closeRenameView}
                    onSubmit={submitRenameView}
                />
            ) : null}
        </>
    )
}
