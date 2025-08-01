import { IconPlusSmall } from '@posthog/icons'
import { lemonToast } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTree, LemonTreeRef } from 'lib/lemon-ui/LemonTree/LemonTree'
import { TreeNodeDisplayIcon } from 'lib/lemon-ui/LemonTree/LemonTreeUtils'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuGroup, DropdownMenuItem, DropdownMenuSeparator } from 'lib/ui/DropdownMenu/DropdownMenu'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { useEffect, useRef } from 'react'
import { urls } from 'scenes/urls'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'
import { PipelineStage } from '~/types'

import { dataWarehouseViewsLogic } from '../../saved_queries/dataWarehouseViewsLogic'
import { renderTableCount } from '../editorSceneLogic'
import { multitabEditorLogic } from '../multitabEditorLogic'
import { isJoined, queryDatabaseLogic } from './queryDatabaseLogic'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import api from 'lib/api'
import { draftsLogic } from '../draftsLogic'

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
        loadDatabase,
        loadJoins,
        setEditingDraft,
        renameDraft,
    } = useActions(queryDatabaseLogic)
    const { deleteDataWarehouseSavedQuery } = useActions(dataWarehouseViewsLogic)

    const multitabLogic = multitabEditorLogic({
        key: `hogQLQueryEditor/${router.values.location.pathname}`,
    })
    const { allTabs } = useValues(multitabLogic)
    const { createTab, selectTab, setTabDraftId } = useActions(multitabLogic)
    const { dataWarehouseSavedQueryMapById } = useValues(dataWarehouseViewsLogic)
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
                    const draft = item.record.draft

                    const existingTab = allTabs.find((tab) => {
                        return tab.draft?.id === draft.id
                    })

                    if (existingTab) {
                        selectTab(existingTab)
                    } else {
                        const associatedView = draft.saved_query_id
                            ? dataWarehouseSavedQueryMapById[draft.saved_query_id]
                            : undefined

                        createTab(draft.query.query, associatedView, undefined, draft)

                        const newTab = allTabs[allTabs.length - 1]
                        if (newTab) {
                            setTabDraftId(newTab.uri.toString(), draft.id)
                        }
                    }
                    return
                }

                // Copy column name when clicking on a column
                if (item && item.record?.type === 'column') {
                    void copyToClipboard(item.record.columnName, item.record.columnName)
                }
            }}
            renderItem={(item) => {
                // Check if item has search matches for highlighting
                const matches = item.record?.searchMatches
                const hasMatches = matches && matches.length > 0

                return (
                    <span className="truncate">
                        {hasMatches && searchTerm ? (
                            <SearchHighlightMultiple
                                string={item.name}
                                substring={searchTerm}
                                className="font-mono text-xs"
                            />
                        ) : (
                            <div className="flex flex-row justify-between gap-1">
                                <span className="truncate font-mono text-xs">{item.name}</span>
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
                                    if (router.values.location.pathname.endsWith(urls.sqlEditor())) {
                                        multitabEditorLogic({
                                            key: `hogQLQueryEditor/${router.values.location.pathname}`,
                                        }).actions.createTab(`SELECT * FROM ${item.name}`)
                                    } else {
                                        router.actions.push(urls.sqlEditor(`SELECT * FROM ${item.name}`))
                                    }
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

                    return (
                        <DropdownMenuGroup>
                            {isSavedQuery && (
                                <>
                                    <DropdownMenuItem
                                        asChild
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            if (router.values.location.pathname.endsWith(urls.sqlEditor())) {
                                                multitabEditorLogic({
                                                    key: `hogQLQueryEditor/${router.values.location.pathname}`,
                                                }).actions.editView(item.record?.view.query.query, item.record?.view)
                                            } else {
                                                router.actions.push(urls.sqlEditor(undefined, item.record?.view.id))
                                            }
                                        }}
                                    >
                                        <ButtonPrimitive menuItem>Edit view definition</ButtonPrimitive>
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
                                        <ButtonPrimitive menuItem>Delete</ButtonPrimitive>
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
                                            void deleteWithUndo({
                                                endpoint: api.dataWarehouseViewLinks.determineDeleteEndpoint(),
                                                object: {
                                                    id: join.id,
                                                    name: `${join.field_name} on ${join.source_table_name}`,
                                                },
                                                callback: () => {
                                                    loadDatabase()
                                                    loadJoins()
                                                },
                                            }).catch((e) => {
                                                lemonToast.error(`Failed to delete warehouse view link: ${e.detail}`)
                                            })
                                        }
                                    }}
                                >
                                    <ButtonPrimitive menuItem>Delete join</ButtonPrimitive>
                                </DropdownMenuItem>
                            </DropdownMenuGroup>
                        )
                    }
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
                                router.actions.push(urls.pipelineNodeNew(PipelineStage.Source))
                            }}
                            data-attr="sql-editor-add-source"
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
