import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { LemonTree, LemonTreeRef } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenuGroup, ContextMenuItem } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenuGroup, DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { useEffect, useRef, useState } from 'react'

import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { joinPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'

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
    const { createFolder, loadFolderIfNotLoaded } = useActions(projectTreeLogic)

    const treeRef = useRef<LemonTreeRef>(null)

    const [expandedFolders, setExpandedFolders] = useState<string[]>([])
    const [touchedFolders, setTouchedFolders] = useState<string[]>([])

    useEffect(() => {
        if (!value) {
            return
        }
        const allFolders = getAllFolderIds(value)
        const newExpandedFolders = allFolders.filter((folder) => !expandedFolders.includes(folder))
        if (newExpandedFolders.length > 0) {
            setExpandedFolders([...expandedFolders, ...newExpandedFolders])
            for (const folder of newExpandedFolders) {
                if (!touchedFolders.includes(folder)) {
                    loadFolderIfNotLoaded(folder)
                }
            }
            const newTouchedFolders = allFolders.filter((folder) => !touchedFolders.includes(folder))
            setTouchedFolders([...touchedFolders, ...newTouchedFolders])
        }
    }, [value, expandedFolders, touchedFolders])

    return (
        <div className={clsx('bg-[white] p-2 border rounded-[var(--radius)] overflow-y-scroll', className)}>
            <LemonTree
                ref={treeRef}
                className="px-0 py-1"
                data={projectTreeOnlyFolders}
                mode="tree"
                tableViewKeys={treeTableKeys}
                defaultSelectedFolderOrNodeId={value ? 'project-tree/' + value : undefined}
                isItemActive={(item) => item.record?.path === value}
                enableMultiSelection={false}
                showFolderActiveState={true}
                checkedItemCount={0}
                onFolderClick={(folder) => {
                    if (folder?.id) {
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
                expandedItemIds={expandedFolders}
                onSetExpandedItemIds={setExpandedFolders}
                enableDragAndDrop={false}
                itemContextMenu={(item) => {
                    if (item.id.startsWith('project-folder-empty/')) {
                        return undefined
                    }
                    if (item.record?.type === 'folder') {
                        return (
                            <ContextMenuGroup>
                                <ContextMenuItem
                                    asChild
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        createFolder(item.record?.path || '')
                                    }}
                                >
                                    <ButtonPrimitive menuItem>New folder</ButtonPrimitive>
                                </ContextMenuItem>
                            </ContextMenuGroup>
                        )
                    }
                    return undefined
                }}
                itemSideAction={(item) => {
                    if (item.id.startsWith('project-folder-empty/')) {
                        return undefined
                    }
                    if (item.record?.type === 'folder') {
                        return (
                            <DropdownMenuGroup>
                                <DropdownMenuItem
                                    asChild
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        createFolder(item.record?.path || '')
                                    }}
                                >
                                    <ButtonPrimitive menuItem>New folder</ButtonPrimitive>
                                </DropdownMenuItem>
                            </DropdownMenuGroup>
                        )
                    }
                    return undefined
                }}
                emptySpaceContextMenu={() => {
                    return (
                        <ContextMenuGroup>
                            <ContextMenuItem
                                asChild
                                onClick={(e) => {
                                    e.stopPropagation()
                                    createFolder('')
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
