import { IconCheckCircle } from '@posthog/icons'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { LemonTree, LemonTreeRef, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenuGroup, ContextMenuItem } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenuGroup, DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { ReactNode, useEffect, useRef, useState } from 'react'

import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { joinPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry } from '~/queries/schema/schema-general'

export interface FolderSelectProps {
    /** The folder to select */
    value?: string
    /** Callback when a folder is selected */
    onChange?: (folder: string) => void
    /** Class name for the component */
    className?: string
}

function getAllFolderIds(path?: string): string[] {
    if (!path) {
        return []
    }
    const splits = splitPath(path)
    return splits.map((_, i) => 'project-folder/' + joinPath(splits.slice(0, i + 1)))
}

/** Input component for selecting a folder */
export function FolderSelect({ value, onChange, className }: FolderSelectProps): JSX.Element {
    const { projectTreeOnlyFolders, treeTableKeys } = useValues(projectTreeLogic)
    const { createFolder, loadFolderIfNotLoaded, rename } = useActions(projectTreeLogic)

    const treeRef = useRef<LemonTreeRef>(null)
    const [selectedFolder, setSelectedFolder] = useState<string | undefined>(value)
    const [expandedFolders, setExpandedFolders] = useState<string[]>(['/'])
    const [touchedFolders, setTouchedFolders] = useState<string[]>([])
    const [localEditingId, setLocalEditingId] = useState<string | null>(null)

    function expandFolders(folder: string): void {
        if (!folder) {
            return
        }
        const allFolders = getAllFolderIds(folder)
        const newExpandedFolders = allFolders.filter((folder) => !expandedFolders.includes(folder))
        if (newExpandedFolders.length > 0) {
            setExpandedFolders([...expandedFolders, ...newExpandedFolders])
            for (const folder of newExpandedFolders) {
                if (!touchedFolders.includes(folder)) {
                    loadFolderIfNotLoaded(folder)
                }
            }
            const newTouchedFolders = allFolders.filter((folder) => !touchedFolders.includes(folder))
            if (newTouchedFolders.length > 0) {
                setTouchedFolders([...touchedFolders, ...newTouchedFolders])
            }
        }
    }

    useEffect(() => {
        value && expandFolders(value)
    }, [value])

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
                                createFolder(item.record?.path || '', false, (folder) => {
                                    // expandFolders(item.record?.path || '')
                                    setLocalEditingId(`project-folder/${folder}`)
                                    onChange?.(folder)
                                })
                            }}
                        >
                            <ButtonPrimitive menuItem>New folder</ButtonPrimitive>
                        </MenuItem>
                        {item.record?.path && item.record?.type === 'folder' ? (
                            <MenuItem
                                asChild
                                onClick={(e) => {
                                    e.stopPropagation()
                                    setLocalEditingId(item.id)
                                }}
                            >
                                <ButtonPrimitive menuItem>Rename</ButtonPrimitive>
                            </MenuItem>
                        ) : null}
                    </MenuGroup>
                )
            }
            return undefined
        }
    }

    return (
        <div className={clsx('bg-surface-primary p-2 border rounded-[var(--radius)] overflow-y-scroll', className)}>
            <LemonTree
                ref={treeRef}
                folderSelectMode
                className="px-0 py-1"
                data={projectTreeOnlyFolders}
                mode="tree"
                tableViewKeys={treeTableKeys}
                defaultSelectedFolderOrNodeId={value ? 'project-folder/' + value : undefined}
                isItemActive={(item) => item.record?.path === value}
                isItemEditing={(item) => item.id === localEditingId}
                onItemNameChange={(item, name) => {
                    if (item.name !== name) {
                        rename(name, item.record as unknown as FileSystemEntry)
                    }
                    // Clear the editing item id when the name changes
                    setLocalEditingId('')
                }}
                // handleStartEditing={(itemId) => setLocalEditingId(itemId) }
                enableMultiSelection={false}
                showFolderActiveState={true}
                checkedItemCount={0}
                onFolderClick={(folder) => {
                    if (folder?.id) {
                        setSelectedFolder(folder?.record?.path)
                        if (!touchedFolders.includes(folder?.id)) {
                            loadFolderIfNotLoaded(folder?.id)
                            setTouchedFolders([...touchedFolders, folder?.id])
                        }
                        if (expandedFolders.includes(folder?.id)) {
                            setExpandedFolders(expandedFolders.filter((id) => id !== folder?.id))
                        } else {
                            setExpandedFolders([...expandedFolders, folder?.id])
                        }
                        if (onChange) {
                            const path = folder?.record?.path || ''
                            if (path) {
                                onChange(path)
                            }
                        }
                    }
                }}
                renderItem={(item) => {
                    return (
                        <span>
                            {item.record?.path === selectedFolder ? (
                                <span className="flex items-center gap-1">
                                    {item.displayName}
                                    <IconCheckCircle className="size-4 text-success" />
                                </span>
                            ) : (
                                item.displayName
                            )}
                        </span>
                    )
                }}
                expandedItemIds={expandedFolders}
                onSetExpandedItemIds={setExpandedFolders}
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
                                    createFolder('', false, (folder) => {
                                        setLocalEditingId(`project-folder/${folder}`)
                                    })
                                }}
                            >
                                <ButtonPrimitive menuItem>New folder</ButtonPrimitive>
                            </ContextMenuItem>
                        </ContextMenuGroup>
                    )
                }}
            />
        </div>
    )
}
