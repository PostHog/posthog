import { useDraggable, useDroppable } from '@dnd-kit/core'
import { CSSProperties, useRef } from 'react'

import { IconChevronRight, IconCircleDashed, IconDocument, IconFolder, IconFolderOpenFilled } from '@posthog/icons'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { buttonPrimitiveVariants } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

import { LemonCheckbox } from '../LemonCheckbox'
import { TreeDataItem } from './LemonTree'

export const ICON_CLASSES = 'text-tertiary size-5 flex items-center justify-center relative'

type TreeNodeDisplayCheckboxProps = {
    item: TreeDataItem
    style?: CSSProperties
    handleCheckedChange?: (checked: boolean, shift: boolean) => void
    className?: string
}

export const TreeNodeDisplayCheckbox = ({
    item,
    handleCheckedChange,
    style,
    className,
}: TreeNodeDisplayCheckboxProps): JSX.Element => {
    const isChecked = item.checked

    return (
        <div
            className={cn('size-5', className)}
            // eslint-disable-next-line react/forbid-dom-props
            style={style}
        >
            <div className={ICON_CLASSES}>
                <LemonCheckbox
                    className={cn(
                        'size-5 ml-[2px] starting:opacity-0 starting:-translate-x-2 translate-x-0 opacity-100 motion-safe:transition-all [transition-behavior:allow-discrete] duration-100',
                        {
                            // Hide the checkbox if...
                            // - the item is disabled from being checked AND
                            // - the item is a folder
                            // - or, the item is a loading indicator
                            // - or, the item is an empty folder
                            hidden:
                                item.disableSelect &&
                                (item.record?.type === 'folder' ||
                                    item.type === 'loading-indicator' ||
                                    item.type === 'empty-folder'),
                        }
                    )}
                    checked={isChecked ?? false}
                    onChange={(checked, event) => {
                        // Just in case
                        if (item.disableSelect) {
                            return
                        }
                        let shift = false
                        if (event.nativeEvent && 'shiftKey' in event.nativeEvent) {
                            shift = !!(event.nativeEvent as PointerEvent).shiftKey
                            if (shift) {
                                event.stopPropagation()
                            }
                        }
                        handleCheckedChange?.(checked, shift)
                    }}
                />
            </div>
        </div>
    )
}

type TreeNodeDisplayIconProps = {
    item: TreeDataItem
    expandedItemIds: string[]
    defaultNodeIcon?: React.ReactNode
    defaultFolderIcon?: React.ReactNode
    size?: 'default' | 'narrow'
}

// Get display item for the tree node
// This is used to render the tree node in the tree view
export const TreeNodeDisplayIcon = ({
    item,
    expandedItemIds,
    defaultNodeIcon,
    defaultFolderIcon,
    size = 'default',
}: TreeNodeDisplayIconProps): JSX.Element => {
    const isOpen = expandedItemIds.includes(item.id)
    const isFolder = item.record?.type === 'folder' || (item.children && item.children.length > 0)
    const isEmptyFolder = item.type === 'empty-folder'
    const isFile = item.record?.type === 'file'
    let iconElement: React.ReactNode = item.icon || defaultNodeIcon || <div />

    // use provided icon as the default icon for source folder nodes
    if (isFolder && !['sources', 'source-folder', 'table', 'view', 'managed-view'].includes(item.record?.type)) {
        iconElement = defaultFolderIcon ? defaultFolderIcon : isOpen ? <IconFolderOpenFilled /> : <IconFolder />
    }

    if (isEmptyFolder) {
        iconElement = <IconCircleDashed />
    }

    if (isFile) {
        iconElement = <IconDocument />
    }

    return (
        <div
            className={cn('h-[var(--lemon-tree-button-height)] flex gap-1 relative items-start ', {
                '-ml-px': size === 'default',
            })}
        >
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
                    'transition-opacity duration-150 top-[var(--lemon-tree-button-icon-offset-top)]'
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

    return (
        // Apply transform to the entire container and make it the drag reference
        <div
            className={cn('relative w-full', props.className)}
            ref={setNodeRef}
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
    isDragging?: boolean
    isRoot?: boolean
    style?: CSSProperties
}

export const TreeNodeDroppable = (props: DroppableProps): JSX.Element => {
    const { setNodeRef, isOver } = useDroppable({ id: props.id })

    return (
        <div
            ref={setNodeRef}
            className={cn(
                'flex flex-col transition-all duration-150 rounded relative z-2 ',
                props.className,
                props.isDroppable && isOver && 'ring-2 ring-inset ring-accent bg-accent-highlight-secondary',
                // If the item is a root item and it's dragging, make it take up the full height
                props.isRoot && props.isDragging && 'h-full'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={props.style}
        >
            {props.children}
        </div>
    )
}

export const InlineEditField = ({
    value,
    handleSubmit,
    style,
    className,
    children,
    inputStyle,
}: {
    value: string
    style?: CSSProperties
    handleSubmit: (value: string) => void
    className?: string
    children: React.ReactNode
    inputStyle?: CSSProperties
}): JSX.Element => {
    const inputRef = useRef<HTMLInputElement>(null)

    useOnMountEffect(() => {
        const timeout = setTimeout(() => {
            if (inputRef.current) {
                inputRef.current.focus()
                inputRef.current.select()
            }
        }, 100)

        return () => clearTimeout(timeout)
    })

    function onSubmit(e: React.FormEvent<HTMLFormElement>): void {
        e.preventDefault()
        handleSubmit(inputRef.current?.value || '')
    }

    function handleBlur(): void {
        handleSubmit(inputRef.current?.value || '')
    }

    return (
        <form
            onSubmit={onSubmit}
            className={cn(
                buttonPrimitiveVariants({ menuItem: true, size: 'base', hasSideActionRight: true }),
                className,
                'bg-fill-button-tertiary-active pl-px'
            )}
        >
            {/* Spacer to offset button padding */}
            <div
                className="h-[var(--lemon-tree-button-height)] bg-transparent pointer-events-none flex-shrink-0 transition-[width] duration-50"
                // eslint-disable-next-line react/forbid-dom-props
                style={style}
            />

            {children}
            <input
                ref={inputRef}
                type="text"
                defaultValue={value}
                onBlur={handleBlur}
                autoFocus
                className="w-full"
                // eslint-disable-next-line react/forbid-dom-props
                style={inputStyle}
                onKeyDown={(e) => {
                    e.stopPropagation()
                    if (e.key === 'Enter') {
                        e.preventDefault()
                        handleSubmit(inputRef.current?.value || '')
                    }
                    if (e.key === 'Escape') {
                        handleSubmit(value)
                    }
                }}
            />
        </form>
    )
}
