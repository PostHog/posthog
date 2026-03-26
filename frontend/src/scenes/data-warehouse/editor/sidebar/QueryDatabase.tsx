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

import { IconTextSize } from 'lib/lemon-ui/icons'
import { LemonTree, LemonTreeRef, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { TreeNodeDisplayIcon } from 'lib/lemon-ui/LemonTree/LemonTreeUtils'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuGroup, DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { POSTHOG_WAREHOUSE } from 'scenes/data-warehouse/editor/connectionSelectorLogic'
import { OutputTab } from 'scenes/data-warehouse/editor/outputPaneLogic'
import { buildQueryForColumnClick } from 'scenes/data-warehouse/editor/sql-utils'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { urls } from 'scenes/urls'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'
import { DatabaseSerializedFieldType } from '~/queries/schema/schema-general'
import { escapePropertyAsHogQLIdentifier } from '~/queries/utils'

import { draftsLogic } from '../draftsLogic'
import { renderTableCount } from '../editorSceneLogic'
import { isJoined, queryDatabaseLogic } from './queryDatabaseLogic'

export const QueryDatabase = (): JSX.Element => {
    const { searchTerm, joinsByFieldName, editingDraftId, displayedTreeData, expandedItemIds, connectionId } =
        useValues(queryDatabaseLogic)
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
    const { deleteJoin } = useActions(dataWarehouseSettingsLogic)
    const { deleteDraft } = useActions(draftsLogic)
    const { setActiveTab, setQueryInput, setSourceQuery } = useActions(sqlEditorLogic)
    const { isEmbeddedMode, sourceQuery } = useValues(sqlEditorLogic)
    const builtTabLogic = useMountedLogic(sqlEditorLogic)
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

    const getTableKindLabel = (item: TreeDataItem): string | null => {
        if (!item.record) {
            return null
        }

        switch (item.record.traversedFieldType ?? item.record.type) {
            case 'lazy-table':
                return 'join'
            case 'virtual-table':
                return 'virtual table'
            case 'materialized_view':
                return 'materialized view'
            case 'managed-view':
                return 'managed view'
            case 'endpoint':
                return 'materialized endpoint'
            case 'view':
            case 'view-table':
                return item.record.view?.is_materialized ? 'materialized view' : 'view'
            case 'table': {
                const tableType = item.record.table?.type
                switch (tableType) {
                    case 'materialized_view':
                        return 'mat view'
                    case 'batch_export':
                        return 'batch export'
                    case 'data_warehouse':
                        return ''
                    case 'posthog':
                        // Return "" to not clutter the interface
                        return ''
                    case 'system':
                        // Return "" to not clutter the interface
                        return ''
                    default:
                        return null
                }
            }
            default:
                return null
        }
    }

    const getEndpointUrl = (item: TreeDataItem): string => {
        const endpointName = item.record?.table?.name ?? item.name
        const versionMatch = endpointName.match(/^(.+)_v(\d+)$/)

        if (versionMatch) {
            return urls.endpoint(versionMatch[1], parseInt(versionMatch[2], 10))
        }

        return urls.endpoint(item.name)
    }

    const treeRef = useRef<LemonTreeRef>(null)
    useEffect(() => {
        setTreeRef(treeRef)
    }, [treeRef, setTreeRef])

    return (
        <LemonTree
            ref={treeRef}
            data={displayedTreeData}
            expandedItemIds={expandedItemIds}
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
                    router.actions.push(urls.sqlEditor({ draftId: item.record.draft.id }))
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
                const tableKindLabel = !isColumn && item.children?.length ? getTableKindLabel(item) : null

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
                                            ['managed-views', 'views', 'sources', 'drafts', 'unsaved-folder'].includes(
                                                item.record?.type
                                            ) && 'font-semibold',
                                            isColumn && 'font-mono text-xs',
                                            'truncate shrink-0'
                                        )}
                                    >
                                        {item.name}
                                    </span>
                                )}
                                {isColumn && columnType ? (
                                    <span className="shrink rounded px-1.5 py-0.5 text-xs text-muted-alt">
                                        {columnType === 'field_traverser' && item?.record?.field.chain
                                            ? formatTraversalChain(item.record.field.chain)
                                            : columnType}
                                    </span>
                                ) : tableKindLabel ? (
                                    <span className="shrink rounded px-1.5 py-0.5 text-xs text-muted-alt">
                                        {tableKindLabel}
                                    </span>
                                ) : null}
                            </div>
                            {renderTableCount(item.record?.row_count)}
                        </div>
                    </span>
                )
            }}
            itemSideAction={(item) => {
                const joinMenu =
                    item.record?.field && item.record?.table
                        ? (() => {
                              const joinKey = `${item.record.table}.${item.record.field.name}`
                              const join = joinsByFieldName[joinKey]

                              if (
                                  !join ||
                                  !isJoined(item.record.field) ||
                                  join.source_table_name !== item.record.table
                              ) {
                                  return null
                              }

                              return (
                                  <DropdownMenuGroup>
                                      <DropdownMenuItem
                                          asChild
                                          onClick={(e) => {
                                              e.stopPropagation()
                                              toggleEditJoinModal(join)
                                          }}
                                      >
                                          <ButtonPrimitive menuItem>Edit</ButtonPrimitive>
                                      </DropdownMenuItem>
                                      <DropdownMenuItem
                                          asChild
                                          onClick={(e) => {
                                              e.stopPropagation()
                                              deleteJoin(join)
                                          }}
                                      >
                                          <ButtonPrimitive menuItem>Delete join</ButtonPrimitive>
                                      </DropdownMenuItem>
                                  </DropdownMenuGroup>
                              )
                          })()
                        : null

                if (joinMenu) {
                    return joinMenu
                }

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
                                    newInternalTab(
                                        urls.sqlEditor({
                                            query: `SELECT * FROM ${escapePropertyAsHogQLIdentifier(item.name)}`,
                                            connectionId:
                                                connectionId && connectionId !== POSTHOG_WAREHOUSE
                                                    ? connectionId
                                                    : undefined,
                                        })
                                    )
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

                if (item.record?.type === 'views') {
                    return (
                        <DropdownMenuGroup>
                            <DropdownMenuItem
                                asChild
                                onClick={(e) => {
                                    e.stopPropagation()
                                    newInternalTab(urls.models())
                                }}
                            >
                                <ButtonPrimitive menuItem>Manage views</ButtonPrimitive>
                            </DropdownMenuItem>
                            <DropdownMenuItem
                                asChild
                                onClick={(e) => {
                                    e.stopPropagation()
                                    newInternalTab(urls.endpoints())
                                }}
                            >
                                <ButtonPrimitive menuItem>Manage endpoints</ButtonPrimitive>
                            </DropdownMenuItem>
                        </DropdownMenuGroup>
                    )
                }

                if (
                    item.record?.type === 'endpoint' ||
                    item.record?.type === 'view' ||
                    item.record?.type === 'managed-view'
                ) {
                    // const viewUrl = getViewUrl(item) ||
                    const url =
                        item.record?.type === 'endpoint'
                            ? getEndpointUrl(item)
                            : urls.sqlEditor({ view_id: item.record?.view.id })
                    const table = item.record?.tableName || item.name
                    const selectAllQuery = `SELECT * FROM ${escapePropertyAsHogQLIdentifier(table)} LIMIT 100`
                    const nextConnectionId =
                        connectionId && connectionId !== POSTHOG_WAREHOUSE ? connectionId : undefined

                    return (
                        <DropdownMenuGroup>
                            <DropdownMenuItem
                                asChild
                                onClick={(e) => {
                                    e.stopPropagation()
                                    if (isEmbeddedMode) {
                                        setActiveTab(OutputTab.Results)
                                        setSourceQuery({
                                            ...sourceQuery,
                                            source: {
                                                ...sourceQuery.source,
                                                connectionId: nextConnectionId,
                                            },
                                        })
                                        setQueryInput(selectAllQuery)
                                        return
                                    }

                                    router.actions.push(
                                        urls.sqlEditor({
                                            query: selectAllQuery,
                                            outputTab: OutputTab.Results,
                                            connectionId: nextConnectionId,
                                        })
                                    )
                                }}
                            >
                                <ButtonPrimitive menuItem>Select all</ButtonPrimitive>
                            </DropdownMenuItem>
                            {!isEmbeddedMode && item.record.type !== 'endpoint' ? (
                                <DropdownMenuItem
                                    asChild
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        router.actions.push(url)
                                    }}
                                >
                                    <ButtonPrimitive menuItem>Edit view definition</ButtonPrimitive>
                                </DropdownMenuItem>
                            ) : null}
                            <DropdownMenuItem
                                asChild
                                onClick={(e) => {
                                    e.stopPropagation()
                                    newInternalTab(url)
                                }}
                            >
                                <ButtonPrimitive menuItem>Edit in new tab</ButtonPrimitive>
                            </DropdownMenuItem>
                            <DropdownMenuItem
                                asChild
                                onClick={(e) => {
                                    e.stopPropagation()
                                    void copyToClipboard(table)
                                }}
                            >
                                <ButtonPrimitive menuItem>Copy name</ButtonPrimitive>
                            </DropdownMenuItem>
                        </DropdownMenuGroup>
                    )
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

                if (item.record?.type === 'sources') {
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
                                newInternalTab(urls.dataWarehouseSourceNew())
                            }}
                            data-attr="sql-editor-add-source"
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
                return <TreeNodeDisplayIcon item={item} expandedItemIds={expandedItemIds} />
            }}
        />
    )
}
