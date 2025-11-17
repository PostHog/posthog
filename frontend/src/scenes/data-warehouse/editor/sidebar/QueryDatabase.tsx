import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useRef } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { LemonTree, LemonTreeRef } from 'lib/lemon-ui/LemonTree/LemonTree'
import { TreeNodeDisplayIcon } from 'lib/lemon-ui/LemonTree/LemonTreeUtils'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuGroup, DropdownMenuItem, DropdownMenuSeparator } from 'lib/ui/DropdownMenu/DropdownMenu'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'

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
    const { deleteDataWarehouseSavedQuery } = useActions(dataWarehouseViewsLogic)
    const { deleteJoin } = useActions(dataWarehouseSettingsLogic)

    const { deleteDraft } = useActions(draftsLogic)

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
                    void copyToClipboard(item.record.columnName, item.record.columnName)
                }

                if (item && item.record?.type === 'unsaved-query') {
                    openUnsavedQuery(item.record)
                }
            }}
            renderItem={(item) => {
                // Check if item has search matches for highlighting
                const matches = item.record?.searchMatches
                const hasMatches = matches && matches.length > 0

                return (
                    <span className="truncate">
                        {hasMatches && searchTerm ? (
                            <SearchHighlightMultiple string={item.name} substring={searchTerm} className="text-xs" />
                        ) : (
                            <div className="flex flex-row gap-1 justify-between">
                                <span
                                    className={cn(
                                        [
                                            'managed-views',
                                            'views',
                                            'sources',
                                            'drafts',
                                            'unsaved-folder',
                                            'endpoints',
                                        ].includes(item.record?.type) && 'font-bold',
                                        item.record?.type === 'column' && 'font-mono text-xs',
                                        'truncate'
                                    )}
                                >
                                    {item.name}
                                </span>
                                {renderTableCount(item.record?.row_count)}
                            </div>
                        )}
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
                                            OutputTab.Endpoint
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
                                router.actions.push(urls.dataWarehouseSourceNew())
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
            renderItemIcon={(item) => {
                if (item.record?.type === 'column') {
                    return <></>
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
