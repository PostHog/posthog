import { IconPlusSmall } from '@posthog/icons'
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
import { editorSizingLogic } from '../editorSizingLogic'
import { multitabEditorLogic } from '../multitabEditorLogic'
import { DatabaseSearchField } from './DatabaseSearchField'
import { queryDatabaseLogic } from './queryDatabaseLogic'

export const QueryDatabase = (): JSX.Element => {
    const { treeData, expandedFolders, expandedSearchFolders, searchTerm } = useValues(queryDatabaseLogic)
    const { setExpandedFolders, toggleFolderOpen, setTreeRef, setExpandedSearchFolders, selectSourceTable } =
        useActions(queryDatabaseLogic)
    const { deleteDataWarehouseSavedQuery } = useActions(dataWarehouseViewsLogic)
    const { sidebarWidth } = useValues(editorSizingLogic)

    const treeRef = useRef<LemonTreeRef>(null)
    useEffect(() => {
        setTreeRef(treeRef)
    }, [treeRef, setTreeRef])

    return (
        <div className="h-full">
            <div
                className="p-1"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ display: sidebarWidth === 0 ? 'none' : undefined }}
            >
                <DatabaseSearchField placeholder="Search database" />
            </div>
            <div className="h-full overflow-y-auto">
                <LemonTree
                    ref={treeRef}
                    data={treeData}
                    expandedItemIds={searchTerm ? expandedSearchFolders : expandedFolders}
                    onSetExpandedItemIds={searchTerm ? setExpandedSearchFolders : setExpandedFolders}
                    onFolderClick={(folder, isExpanded) => {
                        if (folder) {
                            toggleFolderOpen(folder.id, isExpanded)
                        }
                    }}
                    onItemClick={(item) => {
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
                                    <span className="truncate font-mono text-xs">{item.name}</span>
                                )}
                            </span>
                        )
                    }}
                    itemSideAction={(item) => {
                        // Show menu for tables
                        if (item.record?.type === 'table') {
                            return (
                                <DropdownMenuGroup>
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
                        if (item.record?.type === 'view') {
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
                                                    multitabEditorLogic({
                                                        key: `hogQLQueryEditor/${router.values.location.pathname}`,
                                                    }).actions.editView(
                                                        item.record?.view.query.query,
                                                        item.record?.view
                                                    )
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

                        if (item.record?.type === 'sources') {
                            // used to override default icon behavior
                            return null
                        }

                        return undefined
                    }}
                    itemSideActionIcon={(item) => {
                        if (item.record?.type === 'sources') {
                            return (
                                <ButtonPrimitive
                                    iconOnly
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        router.actions.push(urls.pipelineNodeNew(PipelineStage.Source))
                                    }}
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
            </div>
        </div>
    )
}
