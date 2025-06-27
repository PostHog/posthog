import { IconArrowLeft, IconCopy, IconEllipsis, IconPlusSmall, IconServer } from '@posthog/icons'
import { lemonToast, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { DatabaseTableTree } from 'lib/components/DatabaseTableTree/DatabaseTableTree'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonTree, LemonTreeRef } from 'lib/lemon-ui/LemonTree/LemonTree'
import { TreeNodeDisplayIcon } from 'lib/lemon-ui/LemonTree/LemonTreeUtils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuGroup, DropdownMenuItem, DropdownMenuSeparator } from 'lib/ui/DropdownMenu/DropdownMenu'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { useEffect, useRef } from 'react'
import { viewLinkLogic } from 'scenes/data-warehouse/viewLinkLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'
import { Sidebar } from '~/layout/navigation-3000/components/Sidebar'
import { SidebarNavbarItem } from '~/layout/navigation-3000/types'
import { PipelineStage } from '~/types'

import { dataWarehouseViewsLogic } from '../../saved_queries/dataWarehouseViewsLogic'
import { editorSceneLogic, renderTableCount } from '../editorSceneLogic'
import { multitabEditorLogic } from '../multitabEditorLogic'
import { isJoined, queryDatabaseLogic } from './queryDatabaseLogic'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import api from 'lib/api'

export const QueryDatabase = ({ isOpen }: { isOpen: boolean }): JSX.Element => {
    const { featureFlags } = useValues(featureFlagLogic)

    if (featureFlags[FEATURE_FLAGS.SQL_EDITOR_TREE_VIEW]) {
        return <QueryDatabaseTreeView />
    }

    return <QueryDatabaseLegacy isOpen={isOpen} />
}

export const QueryDatabaseTreeView = (): JSX.Element => {
    const { treeData, expandedFolders, expandedSearchFolders, searchTerm, joinsByFieldName } =
        useValues(queryDatabaseLogic)
    const {
        setExpandedFolders,
        toggleFolderOpen,
        setTreeRef,
        setExpandedSearchFolders,
        selectSourceTable,
        toggleEditJoinModal,
        loadDatabase,
        loadJoins,
    } = useActions(queryDatabaseLogic)
    const { deleteDataWarehouseSavedQuery } = useActions(dataWarehouseViewsLogic)

    const treeRef = useRef<LemonTreeRef>(null)
    useEffect(() => {
        setTreeRef(treeRef)
    }, [treeRef, setTreeRef])

    return (
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
                            <div className="flex flex-row justify-between gap-1">
                                <span className="truncate font-mono text-xs">{item.name}</span>
                                {renderTableCount(item.record?.row_count)}
                            </div>
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
                        joinsByFieldName[item.record.columnName] &&
                        joinsByFieldName[item.record.columnName].source_table_name === item.record.table
                    ) {
                        return (
                            <DropdownMenuGroup>
                                <DropdownMenuItem
                                    asChild
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        if (item.record?.columnName) {
                                            toggleEditJoinModal(joinsByFieldName[item.record.columnName])
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
                                            const join = joinsByFieldName[item.record.columnName]
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

const QueryDatabaseLegacy = ({ isOpen }: { isOpen: boolean }): JSX.Element => {
    const navBarItem: SidebarNavbarItem = {
        identifier: Scene.SQLEditor,
        label: 'SQL editor',
        icon: <IconServer />,
        logic: editorSceneLogic,
    }

    return (
        <Sidebar navbarItem={navBarItem} sidebarOverlay={<EditorSidebarOverlay />} sidebarOverlayProps={{ isOpen }} />
    )
}
const EditorSidebarOverlay = (): JSX.Element => {
    const { setSidebarOverlayOpen } = useActions(editorSceneLogic)
    const { sidebarOverlayTreeItems, selectedSchema } = useValues(queryDatabaseLogic)
    const { toggleJoinTableModal, selectSourceTable } = useActions(viewLinkLogic)

    const copy = (): void => {
        if (selectedSchema?.name) {
            void copyToClipboard(selectedSchema.name, 'schema')
        }
    }

    return (
        <div className="flex flex-col h-full">
            <header className="flex flex-row items-center h-10 border-b shrink-0 p-1 gap-1">
                <LemonButton size="small" icon={<IconArrowLeft />} onClick={() => setSidebarOverlayOpen(false)} />
                <Tooltip title="Click to copy">
                    <span
                        className="font-mono cursor-pointer flex-1 whitespace-nowrap overflow-hidden text-ellipsis"
                        onClick={() => copy()}
                    >
                        {selectedSchema?.name}
                    </span>
                </Tooltip>
                <div className="flex">
                    {selectedSchema?.name && (
                        <LemonButton
                            size="small"
                            icon={<IconCopy style={{ color: 'var(--text-secondary)' }} />}
                            noPadding
                            className="ml-1 mr-1"
                            data-attr="copy-icon"
                            onClick={() => copy()}
                        />
                    )}

                    {selectedSchema && 'type' in selectedSchema && selectedSchema.type !== 'managed_view' && (
                        <LemonMenu
                            items={[
                                {
                                    label: 'Add join',
                                    onClick: () => {
                                        if (selectedSchema) {
                                            selectSourceTable(selectedSchema.name)
                                            toggleJoinTableModal()
                                        }
                                    },
                                },
                            ]}
                        >
                            <div>
                                <LemonButton size="small" noPadding icon={<IconEllipsis />} />
                            </div>
                        </LemonMenu>
                    )}
                </div>
            </header>
            <div className="overflow-y-auto flex-1">
                <DatabaseTableTree items={sidebarOverlayTreeItems} />
            </div>
        </div>
    )
}
