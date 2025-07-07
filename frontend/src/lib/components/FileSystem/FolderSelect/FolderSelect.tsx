import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { LemonTree, LemonTreeRef, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenuGroup, ContextMenuItem } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenuGroup, DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { cn } from 'lib/utils/css-classes'
import { ReactNode, useEffect, useRef, useState } from 'react'

import { projectTreeLogic, ProjectTreeLogicProps } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { ScrollableShadows } from '~/lib/components/ScrollableShadows/ScrollableShadows'
import { FileSystemEntry } from '~/queries/schema/schema-general'

export interface FolderSelectProps {
    /** The folder to select */
    value?: string
    /** Callback when a folder is selected */
    onChange?: (selectedFolder: string) => void
    /** Class name for the component */
    className?: string
    /** Root for folder */
    root?: string
    /** Include "products://" in the final path */
    includeProtocol?: boolean
    /** Include root item in the tree as a selectable item */
    includeRoot?: boolean
}

/** Input component for selecting a folder */
let counter = 0

export function FolderSelect({
    value,
    onChange,
    root,
    className,
    includeProtocol,
    includeRoot,
}: FolderSelectProps): JSX.Element {
    const [key] = useState(() => `folder-select-${counter++}`)
    const props: ProjectTreeLogicProps = { key, defaultOnlyFolders: true, root, includeRoot }
    const inputRef = useRef<HTMLInputElement>(null)

    const { searchTerm, expandedSearchFolders, expandedFolders, fullFileSystemFiltered, treeTableKeys, editingItemId } =
        useValues(projectTreeLogic(props))
    const {
        setSearchTerm,
        setExpandedSearchFolders,
        setExpandedFolders,
        createFolder,
        expandProjectFolder,
        setEditingItemId,
        rename,
        toggleFolderOpen,
        deleteItem,
    } = useActions(projectTreeLogic(props))

    const treeRef = useRef<LemonTreeRef>(null)

    useEffect(() => {
        if (includeProtocol) {
            if (value?.startsWith('project://')) {
                expandProjectFolder(value.replace('project://', ''))
            }
        } else {
            expandProjectFolder(value || '')
        }
    }, [value])

    useEffect(() => {
        const timeout = setTimeout(() => {
            if (inputRef.current) {
                inputRef.current?.focus()
            }
        }, 50)
        return () => {
            clearTimeout(timeout)
        }
    }, [])

    function getItemContextMenu(type: 'context' | 'dropdown'): (item: TreeDataItem) => ReactNode | undefined {
        const MenuGroup = type === 'context' ? ContextMenuGroup : DropdownMenuGroup
        const MenuItem = type === 'context' ? ContextMenuItem : DropdownMenuItem

        return function DisplayMenu(item: TreeDataItem) {
            if (item.id.startsWith('project-folder-empty/')) {
                return undefined
            }
            if (item.record?.type === 'folder') {
                return (
                    <MenuGroup>
                        <MenuItem
                            asChild
                            onClick={(e) => {
                                e.stopPropagation()
                                createFolder(item.record?.path || '', true, (folder) => {
                                    onChange?.(folder)
                                })
                            }}
                            data-attr="folder-select-item-menu-new-folder-button"
                        >
                            <ButtonPrimitive menuItem>New folder</ButtonPrimitive>
                        </MenuItem>
                        {item.record?.path && item.record?.type === 'folder' ? (
                            <MenuItem
                                asChild
                                onClick={(e) => {
                                    e.stopPropagation()
                                    setEditingItemId(item.id)
                                }}
                            >
                                <ButtonPrimitive menuItem data-attr="folder-select-item-menu-rename-button">
                                    Rename
                                </ButtonPrimitive>
                            </MenuItem>
                        ) : null}
                        {item.record?.path && item.record?.type === 'folder' ? (
                            <MenuItem
                                asChild
                                onClick={(e) => {
                                    e.stopPropagation()
                                    deleteItem(item.record as unknown as FileSystemEntry, props.key)
                                }}
                            >
                                <ButtonPrimitive menuItem>Delete folder</ButtonPrimitive>
                            </MenuItem>
                        ) : null}
                    </MenuGroup>
                )
            }
            return undefined
        }
    }

    return (
        <div className="flex flex-col gap-2">
            <LemonInput
                type="search"
                placeholder="Search"
                fullWidth
                size="small"
                onChange={(search) => setSearchTerm(search)}
                value={searchTerm}
                data-attr="folder-select-search-input"
                autoFocus
                inputRef={inputRef}
                onKeyDown={(e) => {
                    if (e.key === 'ArrowDown') {
                        e.preventDefault() // Prevent scrolling
                        const visibleItems = treeRef?.current?.getVisibleItems()
                        if (visibleItems && visibleItems.length > 0) {
                            e.currentTarget.blur() // Remove focus from input
                            treeRef?.current?.focusItem(visibleItems[0].id)
                        }
                    }
                }}
            />
            <ScrollableShadows direction="vertical" className={cn('bg-surface-primary border rounded', className)}>
                <LemonTree
                    ref={treeRef}
                    selectMode="folder-only"
                    className="px-0 py-1"
                    data={fullFileSystemFiltered}
                    mode="tree"
                    tableViewKeys={treeTableKeys}
                    defaultSelectedFolderOrNodeId={
                        value?.includes('://') ? value : value ? 'project://' + value : undefined
                    }
                    isItemActive={(item) => item.record?.path === value}
                    isItemEditing={(item) => {
                        return editingItemId === item.id
                    }}
                    onItemNameChange={(item, name) => {
                        if (item.name !== name) {
                            rename(name, item.record as unknown as FileSystemEntry)
                        }
                        // Clear the editing item id when the name changes
                        setEditingItemId('')
                    }}
                    showFolderActiveState={true}
                    checkedItemCount={0}
                    onFolderClick={(folder, isExpanded) => {
                        if (folder) {
                            const folderPath = includeProtocol ? folder.id : folder.record?.path ?? ''

                            if (includeProtocol) {
                                toggleFolderOpen(folder.id, isExpanded)
                                onChange?.(folderPath)
                            } else {
                                toggleFolderOpen(folder.id || '', isExpanded)
                                onChange?.(folderPath)
                            }
                        }
                    }}
                    expandedItemIds={searchTerm ? expandedSearchFolders : expandedFolders}
                    onSetExpandedItemIds={searchTerm ? setExpandedSearchFolders : setExpandedFolders}
                    enableDragAndDrop={false}
                    itemContextMenu={getItemContextMenu('context')}
                    itemSideAction={getItemContextMenu('dropdown')}
                    emptySpaceContextMenu={() => {
                        return (
                            <ContextMenuGroup>
                                <ContextMenuItem
                                    asChild
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        createFolder('', true)
                                    }}
                                >
                                    <ButtonPrimitive menuItem>New folder</ButtonPrimitive>
                                </ContextMenuItem>
                            </ContextMenuGroup>
                        )
                    }}
                    renderItem={(item) => {
                        const isNew =
                            item.record?.created_at && dayjs().diff(dayjs(item.record?.created_at), 'minutes') < 3
                        return (
                            <span className="truncate">
                                <span
                                    className={cn('truncate', {
                                        'font-semibold': item.record?.type === 'folder' && item.type !== 'empty-folder',
                                    })}
                                >
                                    {item.displayName}{' '}
                                    {isNew ? (
                                        <LemonTag type="highlight" size="small" className="ml-1 relative top-[-1px]">
                                            New
                                        </LemonTag>
                                    ) : null}
                                </span>
                            </span>
                        )
                    }}
                />
            </ScrollableShadows>
        </div>
    )
}
