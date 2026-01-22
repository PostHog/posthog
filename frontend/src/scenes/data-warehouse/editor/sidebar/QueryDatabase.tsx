import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useRef } from 'react'

import {
    IconBrackets,
    IconCalculator,
    IconCalendar,
    IconCheck,
    IconClock,
    IconCode,
    IconCode2,
    IconDatabase,
    IconPlusSmall,
} from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { LemonTree, LemonTreeRef } from 'lib/lemon-ui/LemonTree/LemonTree'
import { TreeNodeDisplayIcon } from 'lib/lemon-ui/LemonTree/LemonTreeUtils'
import { IconTextSize } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuGroup, DropdownMenuItem, DropdownMenuSeparator } from 'lib/ui/DropdownMenu/DropdownMenu'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'
import { multitabEditorLogic } from 'scenes/data-warehouse/editor/multitabEditorLogic'
import { buildQueryForColumnClick } from 'scenes/data-warehouse/editor/sql-utils'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'
import { DatabaseSerializedFieldType } from '~/queries/schema/schema-general'

import { dataWarehouseViewsLogic } from '../../saved_queries/dataWarehouseViewsLogic'
import { draftsLogic } from '../draftsLogic'
import { renderTableCount } from '../editorSceneLogic'
import { OutputTab } from '../outputPaneLogic'
import { isJoined, queryDatabaseLogic } from './queryDatabaseLogic'

export const QueryDatabase = (): JSX.Element => {
    const {
        treeData,
        searchTreeData,
        expandedFolders,
        expandedSearchFolders,
        searchTerm,
        joinsByFieldName,
        editingDraftId,
    } = useValues(queryDatabaseLogic)
    const {
        setExpandedFolders,
        toggleFolderOpen,
        setTreeRef,
        setExpandedSearchFolders,
        selectSourceTable,
        toggleEditJoinModal,
        setEditingDraft,
        renameDraft,
        openUnsavedQuery,
        deleteUnsavedQuery,
    } = useActions(queryDatabaseLogic)
    const { deleteDataWarehouseSavedQuery, runDataWarehouseSavedQuery } = useActions(dataWarehouseViewsLogic)
    const { deleteJoin } = useActions(dataWarehouseSettingsLogic)
    const { deleteDraft } = useActions(draftsLogic)
    const { setQueryInput } = useActions(multitabEditorLogic)
    const { selectedQueryColumns } = useValues(multitabEditorLogic)
    const builtTabLogic = useMountedLogic(multitabEditorLogic)
    const formatTraversalChain = (chain?: (string | number)[]): string | null => {
        if (!chain || chain.length === 0) {
            return null
        }

        return chain.map((segment) => String(segment)).join('.')
    }
    const getFieldTypeIconClassName = (fieldType: DatabaseSerializedFieldType): string => {
        switch (fieldType) {
            case 'string':
                return 'text-sky-500'
            case 'integer':
            case 'float':
            case 'decimal':
                return 'text-emerald-500'
            case 'boolean':
                return 'text-purple-500'
            case 'datetime':
                return 'text-amber-500'
            case 'date':
                return 'text-orange-500'
            case 'array':
            case 'json':
                return 'text-teal-500'
            case 'expression':
            case 'field_traverser':
                return 'text-slate-500'
            case 'view':
            case 'materialized_view':
            case 'lazy_table':
            case 'virtual_table':
                return 'text-blue-500'
            default:
                return 'text-tertiary'
        }
    }

    const getFieldTypeIcon = (fieldType?: DatabaseSerializedFieldType): JSX.Element | null => {
        if (!fieldType) {
            return null
        }

        switch (fieldType) {
            case 'string':
                return <IconTextSize className={getFieldTypeIconClassName(fieldType)} />
            case 'integer':
            case 'float':
            case 'decimal':
                return <IconCalculator className={getFieldTypeIconClassName(fieldType)} />
            case 'boolean':
                return <IconCheck className={getFieldTypeIconClassName(fieldType)} />
            case 'datetime':
                return <IconClock className={getFieldTypeIconClassName(fieldType)} />
            case 'date':
                return <IconCalendar className={getFieldTypeIconClassName(fieldType)} />
            case 'array':
            case 'json':
                return <IconBrackets className={getFieldTypeIconClassName(fieldType)} />
            case 'expression':
                return <IconCode className={getFieldTypeIconClassName(fieldType)} />
            case 'field_traverser':
                return <IconCode2 className={getFieldTypeIconClassName(fieldType)} />
            case 'view':
            case 'materialized_view':
            case 'lazy_table':
            case 'virtual_table':
                return <IconDatabase className={getFieldTypeIconClassName(fieldType)} />
            default:
                return <IconCode2 className={getFieldTypeIconClassName(fieldType)} />
        }
    }

    const treeRef = useRef<LemonTreeRef>(null)
    useEffect(() => {
        setTreeRef(treeRef)
    }, [treeRef, setTreeRef])

    return (
        <LemonTree
            ref={treeRef}
            // TODO: Can move this to treedata selector but selectors are maxed out on dependencies
            data={searchTerm ? searchTreeData : treeData}
            expandedItemIds={searchTerm ? expandedSearchFolders : expandedFolders}
            onSetExpandedItemIds={searchTerm ? setExpandedSearchFolders : setExpandedFolders}
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
                // Handle draft clicks - focus existing tab or create new one
                if (item && item.record?.type === 'draft') {
                    router.actions.push(urls.sqlEditor(undefined, undefined, undefined, item.record.draft.id))
                }

                // Copy column name when clicking on a column
                if (item && item.record?.type === 'column') {
                    const currentQueryInput = builtTabLogic.values.queryInput
                    setQueryInput(
                        buildQueryForColumnClick(currentQueryInput, item.record.table, item.record.columnName)
                    )
                }

                if (item && item.record?.type === 'unsaved-query') {
                    openUnsavedQuery(item.record)
                }
            }}
            renderItem={(item) => {
                // Check if item has search matches for highlighting
                const matches = item.record?.searchMatches
                const hasMatches = matches && matches.length > 0
                const isColumn = item.record?.type === 'column'
                const columnType = isColumn ? item.record?.field?.type : null
                const columnKey = isColumn && item.record ? `${item.record.table}.${item.record.columnName}` : null

                return (
                    <span className="truncate">
                        <div className="flex flex-row gap-1 justify-between">
                            <div className="shrink-0 flex min-w-0 items-center gap-2">
                                {hasMatches && searchTerm ? (
                                    <SearchHighlightMultiple
                                        string={item.name}
                                        substring={searchTerm}
                                        className={cn(isColumn && 'font-mono text-xs')}
                                    />
                                ) : (
                                    <span
                                        className={cn(
                                            [
                                                'managed-views',
                                                'views',
                                                'sources',
                                                'drafts',
                                                'unsaved-folder',
                                                'endpoints',
                                            ].includes(item.record?.type) && 'font-semibold',
                                            isColumn && 'font-mono text-xs',
                                            columnKey &&
                                                selectedQueryColumns[columnKey] &&
                                                'underline underline-offset-2',
                                            'truncate shrink-0'
                                        )}
                                    >
                                        {item.name}
                                    </span>
                                )}
                                {isColumn && columnType ? (
                                    <span className="shrink rounded px-1.5 py-0.5 text-xs text-muted-alt">
                                        {columnType}
                                    </span>
                                ) : null}
                            </div>
                            {renderTableCount(item.record?.row_count)}
                        </div>
                    </span>
                )
            }}
            itemSideAction={(item) => {
                // Show menu for drafts
                if (item.record?.type === 'draft') {
                    const draft = item.record.draft
                    return (
                        <DropdownMenuGroup>
                            <DropdownMenuItem
                                asChild
                                onClick={(e) => {
                                    e.stopPropagation()
                                    setEditingDraft(draft.id)
                                }}
                            >
                                <ButtonPrimitive menuItem>Rename</ButtonPrimitive>
                            </DropdownMenuItem>
                            <DropdownMenuItem
                                asChild
                                onClick={(e) => {
                                    e.stopPropagation()
                                    deleteDraft(draft.id)
                                }}
                            >
                                <ButtonPrimitive menuItem className="text-danger">
                                    Delete
                                </ButtonPrimitive>
                            </DropdownMenuItem>
                        </DropdownMenuGroup>
                    )
                }

                // Show menu for tables
                if (item.record?.type === 'table') {
                    return (
                        <DropdownMenuGroup>
                            <DropdownMenuItem
                                asChild
                                onClick={(e) => {
                                    e.stopPropagation()
                                    sceneLogic.actions.newTab(urls.sqlEditor(`SELECT * FROM ${item.name}`))
                                }}
                            >
                                <ButtonPrimitive menuItem>Query</ButtonPrimitive>
                            </DropdownMenuItem>
                            <DropdownMenuItem
                                asChild
                                onClick={(e) => {
                                    e.stopPropagation()
                                    selectSourceTable(item.name)
                                }}
                            >
                                <ButtonPrimitive menuItem>Add join</ButtonPrimitive>
                            </DropdownMenuItem>
                            <DropdownMenuItem
                                asChild
                                onClick={(e) => {
                                    e.stopPropagation()
                                    void copyToClipboard(item.name)
                                }}
                            >
                                <ButtonPrimitive menuItem>Copy table name</ButtonPrimitive>
                            </DropdownMenuItem>
                        </DropdownMenuGroup>
                    )
                }

                // Show menu for views
                if (item.record?.type === 'view' || item.record?.type === 'managed-view') {
                    // Extract view ID from item.id (format: 'view-{id}' or 'search-view-{id}')
                    const viewId = item.id.startsWith('search-view-')
                        ? item.id.replace('search-view-', '')
                        : item.id.replace('view-', '')

                    // Check if this is a saved query (has last_run_at) vs managed view
                    const isSavedQuery = item.record?.isSavedQuery || false
                    const isManagedViewsetQuery = item.record?.view.managed_viewset_kind !== null

                    return (
                        <DropdownMenuGroup>
                            {isSavedQuery && (
                                <>
                                    <DropdownMenuItem
                                        asChild
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            sceneLogic.actions.newTab(urls.sqlEditor(undefined, item.record?.view.id))
                                        }}
                                    >
                                        <ButtonPrimitive
                                            menuItem
                                            tooltipInteractive
                                            tooltipPlacement="right"
                                            disabled={isManagedViewsetQuery}
                                            tooltip={
                                                isManagedViewsetQuery ? (
                                                    <>
                                                        Managed viewset views cannot be edited directly. You can
                                                        enable/disable these views in the{' '}
                                                        <Link to={urls.dataWarehouseManagedViewsets()}>
                                                            Managed Viewsets
                                                        </Link>{' '}
                                                        section.
                                                    </>
                                                ) : undefined
                                            }
                                        >
                                            Edit view definition
                                        </ButtonPrimitive>
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                        asChild
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            selectSourceTable(item.name)
                                        }}
                                    >
                                        <ButtonPrimitive menuItem>Add join</ButtonPrimitive>
                                    </DropdownMenuItem>
                                    {item.record?.view?.is_materialized && (
                                        <DropdownMenuItem
                                            asChild
                                            onClick={(e) => {
                                                e.stopPropagation()
                                                runDataWarehouseSavedQuery(viewId)
                                            }}
                                        >
                                            <ButtonPrimitive
                                                menuItem
                                                disabledReasons={{
                                                    'Materialization is already running':
                                                        item.record?.view?.status === 'Running',
                                                }}
                                            >
                                                Sync now
                                            </ButtonPrimitive>
                                        </DropdownMenuItem>
                                    )}
                                    <DropdownMenuSeparator />
                                    <DropdownMenuItem
                                        asChild
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            deleteDataWarehouseSavedQuery(viewId)
                                        }}
                                    >
                                        <ButtonPrimitive
                                            menuItem
                                            tooltipInteractive
                                            tooltipPlacement="right"
                                            disabled={isManagedViewsetQuery}
                                            tooltip={
                                                isManagedViewsetQuery ? (
                                                    <>
                                                        Managed viewset views cannot be individually deleted. You can
                                                        choose to delete all views in the managed viewset from the{' '}
                                                        <Link to={urls.dataWarehouseManagedViewsets()}>
                                                            Managed Viewsets
                                                        </Link>{' '}
                                                        page.
                                                    </>
                                                ) : undefined
                                            }
                                        >
                                            Delete
                                        </ButtonPrimitive>
                                    </DropdownMenuItem>
                                </>
                            )}
                            <DropdownMenuItem
                                asChild
                                onClick={(e) => {
                                    e.stopPropagation()
                                    void copyToClipboard(item.name)
                                }}
                            >
                                <ButtonPrimitive menuItem>Copy view name</ButtonPrimitive>
                            </DropdownMenuItem>
                        </DropdownMenuGroup>
                    )
                }

                if (item.record?.type === 'column') {
                    if (
                        isJoined(item.record.field) &&
                        joinsByFieldName[`${item.record.table}.${item.record.columnName}`] &&
                        joinsByFieldName[`${item.record.table}.${item.record.columnName}`].source_table_name ===
                            item.record.table
                    ) {
                        return (
                            <DropdownMenuGroup>
                                <DropdownMenuItem
                                    asChild
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        if (item.record?.columnName) {
                                            toggleEditJoinModal(
                                                joinsByFieldName[`${item.record.table}.${item.record.columnName}`]
                                            )
                                        }
                                    }}
                                >
                                    <ButtonPrimitive menuItem>Edit</ButtonPrimitive>
                                </DropdownMenuItem>
                                <DropdownMenuItem
                                    asChild
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        if (item.record?.columnName) {
                                            const join =
                                                joinsByFieldName[`${item.record.table}.${item.record.columnName}`]

                                            deleteJoin(join)
                                        }
                                    }}
                                >
                                    <ButtonPrimitive menuItem>Delete join</ButtonPrimitive>
                                </DropdownMenuItem>
                            </DropdownMenuGroup>
                        )
                    }
                }

                if (item.record?.type === 'unsaved-query') {
                    return (
                        <DropdownMenuGroup>
                            <DropdownMenuItem
                                asChild
                                onClick={(e) => {
                                    e.stopPropagation()
                                    if (item.record) {
                                        openUnsavedQuery(item.record)
                                    }
                                }}
                            >
                                <ButtonPrimitive menuItem>Open</ButtonPrimitive>
                            </DropdownMenuItem>
                            <DropdownMenuItem
                                asChild
                                onClick={(e) => {
                                    e.stopPropagation()
                                    if (item.record) {
                                        deleteUnsavedQuery(item.record)
                                    }
                                }}
                            >
                                <ButtonPrimitive menuItem>Discard</ButtonPrimitive>
                            </DropdownMenuItem>
                        </DropdownMenuGroup>
                    )
                }

                // Show menu for endpoints
                if (item.record?.type === 'endpoint') {
                    return (
                        <DropdownMenuGroup>
                            <DropdownMenuItem
                                asChild
                                onClick={(e) => {
                                    e.stopPropagation()
                                    sceneLogic.actions.newTab(urls.endpoint(item.name))
                                }}
                            >
                                <ButtonPrimitive menuItem>View endpoint</ButtonPrimitive>
                            </DropdownMenuItem>
                            <DropdownMenuItem
                                asChild
                                onClick={(e) => {
                                    e.stopPropagation()
                                    sceneLogic.actions.newTab(
                                        urls.sqlEditor(
                                            item.record?.endpoint?.query.query,
                                            undefined,
                                            undefined,
                                            undefined,
                                            OutputTab.Endpoint,
                                            item.record?.endpoint?.name
                                        )
                                    )
                                }}
                            >
                                <ButtonPrimitive menuItem>Edit endpoint query</ButtonPrimitive>
                            </DropdownMenuItem>
                        </DropdownMenuGroup>
                    )
                }

                if (['sources', 'endpoints'].includes(item.record?.type)) {
                    // used to override default icon behavior
                    return null
                }

                return undefined
            }}
            itemSideActionButton={(item) => {
                if (item.record?.type === 'sources') {
                    return (
                        <ButtonPrimitive
                            iconOnly
                            isSideActionRight
                            className="z-2"
                            onClick={(e) => {
                                e.stopPropagation()
                                sceneLogic.actions.newTab(urls.dataWarehouseSourceNew())
                            }}
                            data-attr="sql-editor-add-source"
                        >
                            <IconPlusSmall className="text-tertiary" />
                        </ButtonPrimitive>
                    )
                }

                if (item.record?.type === 'endpoints') {
                    return (
                        <ButtonPrimitive
                            iconOnly
                            isSideActionRight
                            className="z-2"
                            onClick={(e) => {
                                e.stopPropagation()
                                sceneLogic.actions.newTab(
                                    urls.sqlEditor(undefined, undefined, undefined, undefined, OutputTab.Endpoint)
                                )
                            }}
                            data-attr="sql-editor-add-endpoint"
                        >
                            <IconPlusSmall className="text-tertiary" />
                        </ButtonPrimitive>
                    )
                }
            }}
            renderItemTooltip={(item) => {
                // Show tooltip with full name for items that could be truncated
                const tooltipTypes = ['table', 'view', 'managed-view', 'endpoint', 'draft', 'column', 'unsaved-query']
                if (tooltipTypes.includes(item.record?.type)) {
                    if (item.record?.type === 'column' && item.record?.field?.type === 'field_traverser') {
                        const traversalChain = formatTraversalChain(item.record.field.chain)
                        if (traversalChain) {
                            return `${item.name} → ${traversalChain}`
                        }
                    }
                    return item.name
                }
                if (item.record?.type === 'field-traverser') {
                    const traversalChain = formatTraversalChain(item.record?.field?.chain)
                    if (traversalChain) {
                        return `${item.name} → ${traversalChain}`
                    }
                    return item.name
                }
                return undefined
            }}
            renderItemIcon={(item) => {
                if (item.record?.type === 'column') {
                    return getFieldTypeIcon(item.record.field?.type)
                }
                return (
                    <TreeNodeDisplayIcon
                        item={item}
                        expandedItemIds={searchTerm ? expandedSearchFolders : expandedFolders}
                    />
                )
            }}
        />
    )
}
