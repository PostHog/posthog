import { useDraggable, useDroppable } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import { IconChevronRight } from '@posthog/icons'
import { cn } from 'lib/utils/css-classes'

import { TreeDataItem } from './LemonTree'

type IconProps = {
    item: TreeDataItem
    expandedItemIds: string[]
    defaultNodeIcon?: React.ReactNode
}

// Get the node or folder icon
// If no icon is provided, use a defaultNodeIcon icon
// If no defaultNodeIcon icon is provided, use empty div
export function getIcon({ item, expandedItemIds, defaultNodeIcon }: IconProps): JSX.Element {
    const ICON_CLASSES = 'size-6 aspect-square flex place-items-center'

    const isOpen = expandedItemIds.includes(item.id)
    const isFolder = item.record?.type === 'folder'
    const isFile = item.record?.type === 'file'

    if (isFolder) {
        return (
            // On folder group hover, the chevron icon should fade in and the folder should fade out
            <div className="relative">
                <span
                    className={cn(
                        ICON_CLASSES,
                        'absolute left-0 top-0 opacity-0 group-hover/lemon-tree-button:opacity-100 transition-opacity duration-150'
                    )}
                >
                    <IconChevronRight
                        className={cn('transition-transform scale-75 stroke-2', isOpen ? 'rotate-90' : '')}
                    />
                </span>
                <div
                    className={cn(
                        ICON_CLASSES,
                        'group-hover/lemon-tree-button:opacity-10 transition-opacity duration-150'
                    )}
                >
                    {isOpen ? <IconFolderOpen className="size-4" /> : <IconFolder className="size-4" />}
                </div>
            </div>
        )
    }

    if (isFile) {
        return (
            <>
                <span className={ICON_CLASSES}>
                    <IconFile className="size-4" />
                </span>
            </>
        )
    }

    return (
        <span
            className={cn(ICON_CLASSES, {
                'text-secondary': item.disabledReason,
            })}
        >
            {item.icon || defaultNodeIcon || <div className={ICON_CLASSES} />}
        </span>
    )
}

type DragAndDropProps = {
    id: string
    children: React.ReactNode
}
type DraggableProps = DragAndDropProps & {
    enableDragging: boolean
    className?: string
}

export const TreeNodeDraggable = (props: DraggableProps): JSX.Element => {
    const { attributes, listeners, setNodeRef, transform } = useDraggable({
        id: props.id,
    })
    const style = transform
        ? {
              transform: CSS.Translate.toString(transform),
              zIndex: props.enableDragging ? 10 : undefined,
              opacity: props.enableDragging ? 0.5 : 1,
          }
        : undefined

    return (
        // Apply transform to the entire container and make it the drag reference
        <div
            className={cn('relative', props.className)}
            ref={setNodeRef}
            // eslint-disable-next-line react/forbid-dom-props
            style={style}
            {...(props.enableDragging ? listeners : {})}
        >
            <div className="flex-1" {...attributes}>
                {props.children}
            </div>
        </div>
    )
}

type DroppableProps = DragAndDropProps & {
    isDroppable: boolean
    className?: string
}

export const TreeNodeDroppable = (props: DroppableProps): JSX.Element => {
    const { setNodeRef, isOver } = useDroppable({ id: props.id })

    return (
        <div
            ref={setNodeRef}
            className={cn(
                'transition-all duration-150 rounded',
                props.className,
                props.isDroppable && isOver && 'ring-2 ring-inset ring-accent-primary bg-accent-primary-highlight'
            )}
        >
            {props.children}
        </div>
    )
}

export const IconFolderOpen = (props: { className?: string }): JSX.Element => {
    return (
        <svg
            xmlns="http://www.w3.org/2000/svg"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={props.className}
        >
            <path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2" />
        </svg>
    )
}
export const IconFolder = (props: { className?: string }): JSX.Element => {
    return (
        <svg
            xmlns="http://www.w3.org/2000/svg"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={props.className}
        >
            <path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />
        </svg>
    )
}

export const IconFile = (props: { className?: string }): JSX.Element => {
    return (
        <svg
            xmlns="http://www.w3.org/2000/svg"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={props.className}
        >
            <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
            <path d="M14 2v4a2 2 0 0 0 2 2h4" />
        </svg>
    )
}

export const IconCircleDashed = (props: { className?: string }): JSX.Element => {
    return (
        <svg
            xmlns="http://www.w3.org/2000/svg"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={props.className}
        >
            <path d="M10.1 2.182a10 10 0 0 1 3.8 0" />
            <path d="M13.9 21.818a10 10 0 0 1-3.8 0" />
            <path d="M17.609 3.721a10 10 0 0 1 2.69 2.7" />
            <path d="M2.182 13.9a10 10 0 0 1 0-3.8" />
            <path d="M20.279 17.609a10 10 0 0 1-2.7 2.69" />
            <path d="M21.818 10.1a10 10 0 0 1 0 3.8" />
            <path d="M3.721 6.391a10 10 0 0 1 2.7-2.69" />
            <path d="M6.391 20.279a10 10 0 0 1-2.69-2.7" />
        </svg>
    )
}
