import { useDraggable, useDroppable } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import { IconChevronRight, IconDocument, IconFolder, IconFolderOpen } from '@posthog/icons'
import { cn } from 'lib/utils/css-classes'

import { LemonCheckbox } from '../LemonCheckbox'
import { TreeDataItem } from './LemonTree'

type IconProps = {
    item: TreeDataItem
    expandedItemIds: string[]
    checkedItems: string[]
    defaultNodeIcon?: React.ReactNode
    enableMultiSelection?: boolean
    handleCheckedChange?: (checked: boolean) => void
}

// Get the node or folder icon
// If no icon is provided, use a defaultNodeIcon icon
// If no defaultNodeIcon icon is provided, use empty div
export function getIcon({
    item,
    expandedItemIds,
    defaultNodeIcon,
    enableMultiSelection = false,
    checkedItems,
    handleCheckedChange,
}: IconProps): JSX.Element {
    const ICON_CLASSES = 'text-tertiary pt-0.5'

    const isOpen = expandedItemIds.includes(item.id)
    const isFolder = item.record?.type === 'folder'
    const isFile = item.record?.type === 'file'
    const isChecked = checkedItems.includes(item.id)
    let iconElement: React.ReactNode = item.icon || defaultNodeIcon || <div />

    if (isFolder) {
        iconElement = isOpen ? <IconFolderOpen /> : <IconFolder />
    }

    if (isFile) {
        iconElement = <IconDocument />
    }

    return (
        <div className="relative group/lemon-tree-icon-group">
            {(enableMultiSelection || isChecked) && (
                <div
                    className={cn(
                        ICON_CLASSES,
                        'z-3 absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 group-hover/lemon-tree-icon-group:opacity-100 transition-opacity duration-150',
                        {
                            'opacity-0': !checkedItems.includes(item.id),
                            'opacity-100': checkedItems.includes(item.id),
                        }
                    )}
                >
                    <LemonCheckbox
                        checked={checkedItems.includes(item.id)}
                        onChange={(checked, e) => {
                            e?.stopPropagation()
                            handleCheckedChange?.(checked)
                        }}
                    />
                </div>
            )}
            {isFolder && (
                <div
                    className={cn(
                        ICON_CLASSES,
                        'z-2 absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 opacity-0 group-hover/lemon-tree-button:opacity-100 transition-opacity duration-150'
                    )}
                >
                    <IconChevronRight className={cn('transition-transform size-4', isOpen ? 'rotate-90' : '')} />
                </div>
            )}
            <div
                className={cn(
                    ICON_CLASSES,
                    {
                        'text-tertiary': item.disabledReason,
                        'group-hover/lemon-tree-button:opacity-0': isFolder || enableMultiSelection,
                    },
                    'transition-opacity duration-150'
                )}
            >
                {iconElement}
            </div>
        </div>
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
            className={cn('relative w-full', props.className)}
            ref={setNodeRef}
            // eslint-disable-next-line react/forbid-dom-props
            style={style}
            {...(props.enableDragging ? listeners : {})}
        >
            <div
                {...attributes}
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    height: '100%',
                }}
            >
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
                props.isDroppable && isOver && 'ring-2 ring-inset ring-accent bg-accent-highlight-secondary'
            )}
        >
            {props.children}
        </div>
    )
}
