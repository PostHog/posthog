import { useDraggable, useDroppable } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import { IconChevronRight, IconDocument, IconFolder, IconFolderOpen } from '@posthog/icons'
import { Icon } from 'lib/ui/Icon/Icon'
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
    const ICON_CLASSES = 'text-secondary'

    const isOpen = expandedItemIds.includes(item.id)
    const isFolder = item.record?.type === 'folder'
    const isFile = item.record?.type === 'file'

    if (isFolder) {
        return (
            // On folder group hover, the chevron icon should fade in and the folder should fade out
            <div className="relative">
                <Icon
                    size="sm"
                    className={cn(
                        ICON_CLASSES,
                        'absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 opacity-0 group-hover/lemon-tree-button:opacity-100 transition-opacity duration-150'
                    )}
                >
                    <IconChevronRight className={cn('transition-transform size-4', isOpen ? 'rotate-90' : '')} />
                </Icon>
                <Icon
                    className={cn(
                        ICON_CLASSES,
                        'group-hover/lemon-tree-button:opacity-10 transition-opacity duration-150'
                    )}
                >
                    {isOpen ? <IconFolderOpen /> : <IconFolder />}
                </Icon>
            </div>
        )
    }

    if (isFile) {
        return (
            <>
                <Icon className={ICON_CLASSES}>
                    <IconDocument />
                </Icon>
            </>
        )
    }

    return (
        <Icon
            className={cn(ICON_CLASSES, {
                'text-tertiary': item.disabledReason,
            })}
        >
            {item.icon || defaultNodeIcon || <div className={ICON_CLASSES} />}
        </Icon>
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
    const {
        attributes,
        listeners: originalListeners,
        setNodeRef,
        transform,
    } = useDraggable({
        id: props.id,
    })

    // Filter out the Enter key from drag listeners
    const listeners = props.enableDragging
        ? Object.fromEntries(
              Object.entries(originalListeners || {}).map(([key, handler]) => [
                  key,
                  (e: any) => {
                      if (e.key === 'Enter') {
                          return
                      }
                      handler(e)
                  },
              ])
          )
        : {}

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
