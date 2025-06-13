import { IconArrowLeft, IconCopy, IconEllipsis, IconFolderPlus, IconPlusSmall, IconServer } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
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
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { PipelineStage } from '~/types'

import { dataWarehouseViewsLogic } from '../../saved_queries/dataWarehouseViewsLogic'
import { editorSceneLogic, renderTableCount } from '../editorSceneLogic'
import { editorSizingLogic } from '../editorSizingLogic'
import { multitabEditorLogic } from '../multitabEditorLogic'
import { DatabaseSearchField } from './DatabaseSearchField'
import { queryDatabaseLogic, UNFILED_SAVED_QUERIES_PATH } from './queryDatabaseLogic'

export const QueryDatabase = ({ isOpen }: { isOpen: boolean }): JSX.Element => {
    const { featureFlags } = useValues(featureFlagLogic)

    if (featureFlags[FEATURE_FLAGS.SQL_EDITOR_TREE_VIEW]) {
        return <QueryDatabaseTreeView />
    }

    return <QueryDatabaseLegacy isOpen={isOpen} />
}

const QueryDatabaseTreeView = (): JSX.Element => {
    const { treeDataFinal, expandedFolders, expandedSearchFolders, searchTerm, viableItems, editingItemId } =
        useValues(queryDatabaseLogic)
    const {
        setExpandedFolders,
        toggleFolderOpen,
        setTreeRef,
        setExpandedSearchFolders,
        selectSourceTable,
        moveItem,
        addFolder,
        setEditingItemId,
        rename,
        deleteItem,
    } = useActions(queryDatabaseLogic)
    const { deleteDataWarehouseSavedQuery } = useActions(dataWarehouseViewsLogic)
    const { sidebarWidth } = useValues(editorSizingLogic)

    const treeRef = useRef<LemonTreeRef>(null)
    useEffect(() => {
        setTreeRef(treeRef)
    }, [treeRef, setTreeRef])

    // Helper function to find any file or folder in the unfiled tree by ID
    const findItemById = (fileId: string): FileSystemEntry | undefined => {
        return viableItems.find(
            (item) =>
                item.path.startsWith(UNFILED_SAVED_QUERIES_PATH) &&
                `file-${item.path.replace(UNFILED_SAVED_QUERIES_PATH + '/', '')}` === fileId
        )
    }

    return (
        <div className="flex-1 flex flex-col h-full overflow-hidden">
            <div
                className="p-1"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ display: sidebarWidth === 0 ? 'none' : undefined }}
            >
                <DatabaseSearchField placeholder="Search database" />
            </div>
            <div className="overflow-y-auto flex-1 min-h-0">
                <LemonTree
                    ref={treeRef}
                    data={treeDataFinal}
                    expandedItemIds={searchTerm ? expandedSearchFolders : expandedFolders}
                    onSetExpandedItemIds={searchTerm ? setExpandedSearchFolders : setExpandedFolders}
                    isItemEditing={(item) => {
                        return editingItemId === item.id
                    }}
                    onItemNameChange={(item, name) => {
                        if (item.name !== name && item.record?.file) {
                            rename(name, item.record.file)
                        }
                        // Clear the editing item id when the name changes
                        setEditingItemId('')
                    }}
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

                        // Files now expand to show columns instead of opening
                        // Removed the file opening behavior to allow expansion
                    }}
                    enableDragAndDrop={!searchTerm}
                    onDragEnd={(dragEvent) => {
                        const oldId = dragEvent.active.id as string
                        const newId = dragEvent.over?.id as string

                        if (oldId === newId || !newId) {
                            return false
                        }

                        // Only allow drag and drop within Files section
                        const isFileItem = (id: string): boolean => id.startsWith('file-') || id === 'views'

                        if (!isFileItem(oldId) || !isFileItem(newId)) {
                            return false
                        }

                        // Find the dragged item (file or folder)
                        const draggedItem = findItemById(oldId)

                        if (!draggedItem) {
                            return false
                        }

                        // Prevent dropping a folder into itself or its children
                        if (draggedItem.type === 'folder' && newId.startsWith('file-')) {
                            const targetItem = findItemById(newId)
                            if (targetItem && targetItem.path.startsWith(draggedItem.path + '/')) {
                                return false // Can't move folder into its own child
                            }
                        }

                        // Determine target folder
                        let targetFolderPath = UNFILED_SAVED_QUERIES_PATH

                        if (newId.startsWith('file-') && newId !== oldId) {
                            // Find the target item
                            const targetItem = findItemById(newId)

                            if (targetItem?.type === 'folder') {
                                // Dropping on a folder
                                targetFolderPath = targetItem.path
                            } else if (targetItem) {
                                // Dropping on a file - move to same folder as target file
                                const targetPathParts = targetItem.path.split('/')
                                targetPathParts.pop() // Remove filename/foldername
                                targetFolderPath = targetPathParts.join('/')
                            }
                        }

                        // Calculate new path for the dragged item
                        const draggedItemNameParts = draggedItem.path.split('/')
                        const itemName = draggedItemNameParts.pop() || 'untitled'
                        const newPath = targetFolderPath ? `${targetFolderPath}/${itemName}` : itemName

                        // Move the item using projectTreeDataLogic
                        moveItem(draggedItem, newPath, false, 'query-database')

                        return true
                    }}
                    isItemDraggable={(item) => {
                        // Files and folders in the Files section are draggable
                        const draggable =
                            item.id.startsWith('file-') &&
                            (item.record?.type === 'view' || item.record?.type === 'folder')
                        return draggable
                    }}
                    isItemDroppable={(item) => {
                        // Can drop on the Files folder itself or on file/folder items within Files
                        const droppable =
                            item.id === 'views' ||
                            (item.id.startsWith('file-') && item.record?.type === 'folder') ||
                            (item.id.startsWith('file-') && item.record?.type === 'view')

                        return droppable
                    }}
                    renderItem={(item) => {
                        return (
                            <span className="truncate">
                                {searchTerm ? (
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
                                                    if (item.record?.view) {
                                                        deleteDataWarehouseSavedQuery(item.record.view.id)
                                                        if (item.record?.file) {
                                                            deleteItem(item.record.file, 'query-database')
                                                        }
                                                    }
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

                        if (item.record?.type === 'sources' || item.id === 'views') {
                            // used to override default icon behavior
                            return null
                        }

                        // Show menu for files
                        if (item.record?.type === 'folder') {
                            return (
                                <DropdownMenuGroup>
                                    <DropdownMenuItem
                                        asChild
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            setEditingItemId(item.id)
                                        }}
                                    >
                                        <ButtonPrimitive menuItem>Rename</ButtonPrimitive>
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                        asChild
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            deleteItem(item.record as unknown as FileSystemEntry, 'query-database')
                                        }}
                                    >
                                        <ButtonPrimitive menuItem>Delete folder</ButtonPrimitive>
                                    </DropdownMenuItem>
                                </DropdownMenuGroup>
                            )
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
                        if (item.id === 'views') {
                            return (
                                <ButtonPrimitive
                                    iconOnly
                                    isSideActionRight
                                    className="z-2"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        addFolder()
                                    }}
                                >
                                    <IconFolderPlus className="text-tertiary" />
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
