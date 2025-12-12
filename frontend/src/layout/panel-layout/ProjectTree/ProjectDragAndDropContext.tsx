import {
    DndContext,
    DragEndEvent,
    DragOverlay,
    DragStartEvent,
    MouseSensor,
    TouchSensor,
    useDndMonitor,
    useSensor,
    useSensors,
} from '@dnd-kit/core'
import { useActions, useValues } from 'kea'
import { createContext, useContext, useState } from 'react'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import type { FileSystemEntry } from '~/queries/schema/schema-general'

import { iconForType } from './defaultTree'
import { projectTreeDataLogic } from './projectTreeDataLogic'
import { projectTreeLogic } from './projectTreeLogic'
import { calculateMovePath } from './utils'

export type ProjectDragIdentifier = {
    type?: string
    ref?: string
    href?: string
    path?: string
    protocol?: string
}

export type ProjectDragData = {
    identifier: ProjectDragIdentifier
    logicKey?: string
    checkedItemIds?: string[]
}

type DragContextValue = {
    activeItem: FileSystemEntry | null
}

const ProjectDragContext = createContext<DragContextValue>({ activeItem: null })

const DROPPABLE_SCOPE_SEPARATOR = '::'

const getDroppableFolderId = (protocol: string, path: string, scope: string = 'project-tree'): string =>
    `${scope}${DROPPABLE_SCOPE_SEPARATOR}${protocol}${path}`

// Compat helper used by older drag-and-drop consumers
export const getScopedDndId = getDroppableFolderId

const getFolderFromDroppableId = (id?: string | number): string => {
    if (!id) {
        return ''
    }

    const stringId = String(id)
    const scopedId = stringId.includes(DROPPABLE_SCOPE_SEPARATOR)
        ? stringId.substring(stringId.indexOf(DROPPABLE_SCOPE_SEPARATOR) + DROPPABLE_SCOPE_SEPARATOR.length)
        : stringId

    if (scopedId.includes('://')) {
        return scopedId.substring(scopedId.indexOf('://') + 3)
    }

    if (scopedId.startsWith('project/')) {
        return ''
    }

    return scopedId
}

const getIdentifierFromEntry = (entry: FileSystemEntry): ProjectDragIdentifier => ({
    type: entry.type,
    ref: entry.ref,
    href: entry.href,
    path: entry.path,
    protocol: (entry as unknown as Record<string, string | undefined>).protocol ?? 'project://',
})

export function useProjectDragState(): DragContextValue {
    return useContext(ProjectDragContext)
}

export function ProjectDragAndDropProvider({ children }: { children: React.ReactNode }): JSX.Element {
    const { itemsByRef, itemsByHref, itemsByPath } = useValues(projectTreeDataLogic)
    const { moveItem } = useActions(projectTreeDataLogic)
    const sensors = useSensors(
        useSensor(MouseSensor, {
            activationConstraint: { distance: 10 },
        }),
        useSensor(TouchSensor, {
            activationConstraint: { delay: 250, tolerance: 5 },
        })
    )
    const [activeItem, setActiveItem] = useState<FileSystemEntry | null>(null)

    const resolveEntry = (identifier?: ProjectDragIdentifier): FileSystemEntry | null => {
        if (!identifier) {
            return null
        }

        if (identifier.type && identifier.ref) {
            const keyed = itemsByRef[`${identifier.type}::${identifier.ref}`]
            if (keyed) {
                return keyed
            }
        }

        if (identifier.href) {
            const keyed = itemsByHref[identifier.href]
            if (keyed) {
                return keyed
            }
        }

        if (identifier.path !== undefined) {
            return itemsByPath[identifier.path] ?? null
        }

        return null
    }

    const handleDragStart = (event: DragStartEvent): void => {
        const identifier = (event.active.data?.current as ProjectDragData | null)?.identifier
        const entry = resolveEntry(identifier)

        if (entry) {
            setActiveItem(entry)
        }
    }

    const handleDragEnd = (event: DragEndEvent): void => {
        const dragData = event.active.data?.current as ProjectDragData | undefined

        setActiveItem(null)

        if (!dragData || !event.over?.id) {
            return
        }

        const destinationFolder = getFolderFromDroppableId(event.over.id)
        const entry = resolveEntry(dragData.identifier)

        if (!entry) {
            return
        }

        if (dragData.checkedItemIds && dragData.checkedItemIds.length > 0) {
            const logicInstance =
                projectTreeLogic.findMounted({
                    key: dragData.logicKey ?? 'project-tree',
                }) ||
                projectTreeLogic({
                    key: dragData.logicKey ?? 'project-tree',
                    root: dragData.identifier.protocol ?? 'project://',
                })

            logicInstance?.actions.moveCheckedItems(destinationFolder)
            return
        }

        const { newPath, isValidMove } = calculateMovePath(entry, destinationFolder)

        if (isValidMove) {
            moveItem(entry, newPath, false, dragData.logicKey ?? 'project-tree')
        }
    }

    function ProjectDragMonitor(): null {
        useDndMonitor({
            onDragStart: handleDragStart,
            onDragEnd: handleDragEnd,
            onDragCancel: () => setActiveItem(null),
        })
        return null
    }

    return (
        <ProjectDragContext.Provider value={{ activeItem }}>
            <DndContext sensors={sensors}>
                <ProjectDragMonitor />
                {children}
                <DragOverlay dropAnimation={null}>
                    {activeItem ? (
                        <ButtonPrimitive className="flex items-center gap-2 rounded border border-border bg-surface px-3 py-2 shadow-lg">
                            <span className="shrink-0 text-primary">
                                {iconForType((activeItem.type as any) || 'default_icon_type')}
                            </span>
                            <span className="truncate font-medium text-primary">
                                {('name' in activeItem && activeItem.name) || activeItem.path || 'Unnamed item'}
                            </span>
                        </ButtonPrimitive>
                    ) : null}
                </DragOverlay>
            </DndContext>
        </ProjectDragContext.Provider>
    )
}

export function projectDroppableId(path: string, protocol: string = 'project://', scope?: string): string {
    return getDroppableFolderId(protocol, path, scope)
}

export function projectDroppableFolder(path: string | undefined): string {
    return getFolderFromDroppableId(path)
}

export function projectDragDataFromEntry(
    entry: FileSystemEntry,
    logicKey?: string,
    checkedItemIds?: string[]
): ProjectDragData {
    return {
        identifier: getIdentifierFromEntry(entry),
        logicKey,
        checkedItemIds,
    }
}
