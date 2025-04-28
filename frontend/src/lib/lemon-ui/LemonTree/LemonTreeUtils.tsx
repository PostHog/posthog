import { useDraggable, useDroppable } from '@dnd-kit/core'
import { IconChevronRight, IconDocument, IconFolder, IconFolderOpenFilled } from '@posthog/icons'
import { buttonVariants } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { CSSProperties, useEffect, useRef } from 'react'

import { LemonCheckbox } from '../LemonCheckbox'
import { TreeDataItem } from './LemonTree'

export const ICON_CLASSES = 'text-tertiary size-5 flex items-center justify-center'

type TreeNodeDisplayIconWrapperProps = {
    item: TreeDataItem
    expandedItemIds?: string[]
    defaultNodeIcon?: React.ReactNode
    handleClick: (item: TreeDataItem) => void
    enableMultiSelection: boolean
    defaultOffset: number
    multiSelectionOffset: number
    checkedItemCount?: number
    onItemChecked?: (id: string, checked: boolean, shift: boolean) => void
}

export const TreeNodeDisplayIconWrapper = ({
    item,
    expandedItemIds,
    defaultNodeIcon,
    handleClick,
    enableMultiSelection,
    checkedItemCount,
    onItemChecked,
    defaultOffset,
    multiSelectionOffset,
}: TreeNodeDisplayIconWrapperProps): JSX.Element => {
    return (
        <>
            {/* 
                The idea here is:
                - if there are no checked items, on hover of the display icon, show the checkbox INSTEAD of the display icon
                - if there are checked items, show both the checkbox and the display icon ([checkbox] [display icon] [button]) 
            */}
            <div
                className={cn(
                    'absolute flex items-center justify-center bg-transparent flex-shrink-0 h-[var(--button-height-base)] z-3',
                    {
                        // Apply group class only when there are no checked items
                        'group/lemon-tree-icon-wrapper': checkedItemCount === 0,
                    }
                )}
            >
                <TreeNodeDisplayCheckbox
                    item={item}
                    handleCheckedChange={(checked, shift) => {
                        onItemChecked?.(item.id, checked, shift)
                    }}
                    className={cn('absolute z-2', {
                        // Apply hidden class only when hovering the (conditional)group and there are no checked items
                        'hidden group-hover/lemon-tree-icon-wrapper:block transition-all duration-50':
                            checkedItemCount === 0,
                    })}
                    style={{
                        left: `${defaultOffset}px`,
                    }}
                />

                <div
                    className="absolute transition-all duration-50"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        // If multi-selection is enabled, we need to offset the icon to the right to make space for the checkbox
                        left:
                            enableMultiSelection && !item.disableSelect
                                ? `${multiSelectionOffset}px`
                                : `${defaultOffset}px`,
                    }}
                    // Since we need to make this element hoverable, we cannot pointer-events: none, so we pass onClick to mimic the sibling button click
                    onClick={() => {
                        handleClick(item)
                    }}
                >
                    <TreeNodeDisplayIcon
                        item={item}
                        expandedItemIds={expandedItemIds ?? []}
                        defaultNodeIcon={defaultNodeIcon}
                    />
                </div>
            </div>
        </>
    )
}

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
                    className={cn('size-5 ml-[2px]', {
                        // Hide the checkbox if the item is disabled from being checked and is a folder
                        // When searching we disable folders from being checked
                        hidden: item.disableSelect && item.record?.type === 'folder',
                    })}
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
}

// Get display item for the tree node
// This is used to render the tree node in the tree view
export const TreeNodeDisplayIcon = ({
    item,
    expandedItemIds,
    defaultNodeIcon,
}: TreeNodeDisplayIconProps): JSX.Element => {
    const isOpen = expandedItemIds.includes(item.id)
    const isFolder = item.record?.type === 'folder'
    const isFile = item.record?.type === 'file'
    let iconElement: React.ReactNode = item.icon || defaultNodeIcon || <div />

    if (isFolder) {
        iconElement = isOpen ? <IconFolderOpenFilled /> : <IconFolder />
    }

    if (isFile) {
        iconElement = <IconDocument />
    }

    return (
        <div
            className={cn('flex gap-1 relative [&_svg]:size-4', {
                // Don't hide the icon on hover if the item is disabled from being checked
                'group-hover/lemon-tree-icon-wrapper:opacity-0': !item.disableSelect,
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
}

export const TreeNodeDroppable = (props: DroppableProps): JSX.Element => {
    const { setNodeRef, isOver } = useDroppable({ id: props.id })

    return (
        <div
            ref={setNodeRef}
            className={cn(
                'flex flex-col transition-all duration-150 rounded',
                props.className,
                props.isDroppable && isOver && 'ring-2 ring-inset ring-accent bg-accent-highlight-secondary'
            )}
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
}: {
    value: string
    style?: CSSProperties
    handleSubmit: (value: string) => void
    className?: string
}): JSX.Element => {
    const inputRef = useRef<HTMLInputElement>(null)

    useEffect(() => {
        const timeout = setTimeout(() => {
            if (inputRef.current) {
                inputRef.current.focus()
                inputRef.current.select()
            }
        }, 100)
        return () => clearTimeout(timeout)
    }, [])

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
            className={cn(buttonVariants({ menuItem: true, size: 'base', sideActionLeft: true }), className)}
        >
            {/* Spacer to offset button padding */}
            <div
                className="h-full bg-transparent pointer-events-none flex-shrink-0 transition-[width] duration-50"
                // eslint-disable-next-line react/forbid-dom-props
                style={style}
            />
            <input
                ref={inputRef}
                type="text"
                defaultValue={value}
                onBlur={handleBlur}
                autoFocus
                className="w-full"
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
