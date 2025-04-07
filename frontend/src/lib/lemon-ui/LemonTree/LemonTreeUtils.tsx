import { useDraggable, useDroppable } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import { IconChevronRight, IconDocument, IconFolder, IconFolderOpen } from '@posthog/icons'
import { cn } from 'lib/utils/css-classes'

import { LemonCheckbox } from '../LemonCheckbox'
import { TreeDataItem } from './LemonTree'

const ICON_CLASSES = 'text-tertiary size-5 flex items-center justify-center'

type CheckboxProps = {
    item: TreeDataItem
    expandedItemIds: string[]
    enableMultiSelection?: boolean
    handleCheckedChange?: (checked: boolean) => void
}

// Render an icon or checkbox
export function renderTreeNodeDisplayCheckbox({
    item,
    enableMultiSelection = false,
    handleCheckedChange,
}: CheckboxProps): JSX.Element {
    const isChecked = !!item.checked

    return (
        <>
            {((enableMultiSelection && !item.disableSelect) || isChecked) && (
                <div className={cn(ICON_CLASSES, 'z-3 relative')}>
                    <LemonCheckbox
                        className="size-5 ml-[2px]"
                        checked={item.checked ?? false}
                        onChange={(checked) => {
                            handleCheckedChange?.(checked)
                        }}
                    />
                </div>
            )}
        </>
    )
}

type IconProps = {
    item: TreeDataItem
    expandedItemIds: string[]
    defaultNodeIcon?: React.ReactNode
}

// Get display item for the tree node
// This is used to render the tree node in the tree view
export function renderTreeNodeDisplayIcon({ item, expandedItemIds, defaultNodeIcon }: IconProps): JSX.Element {
    const isOpen = expandedItemIds.includes(item.id)
    const isFolder = item.record?.type === 'folder'
    const isFile = item.record?.type === 'file'
    let iconElement: React.ReactNode = item.icon || defaultNodeIcon || <div />

    if (isFolder) {
        iconElement = isOpen ? <IconFolderOpen /> : <IconFolder />
    }

    if (isFile) {
        iconElement = <IconDocument />
    }

    return (
        <div className="flex gap-1 relative group/lemon-tree-icon-group [&_svg]:size-4">
            {isFolder && (
                <div
                    className={cn(
                        ICON_CLASSES,
                        'z-2 absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 opacity-0 group-hover/lemon-tree-button-group:opacity-100 transition-opacity duration-150'
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
                        'group-hover/lemon-tree-button-group:opacity-0': isFolder,
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
