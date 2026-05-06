import { useDraggable, useDroppable } from '@dnd-kit/core'
import { CSSProperties, useEffect, useRef, useState } from 'react'

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
    if (
        isFolder &&
        !['sources', 'source-folder', 'table', 'view', 'managed-view', 'endpoint'].includes(item.record?.type)
    ) {
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

export type TreeDropPosition = 'before' | 'after' | 'onto'

type DroppableProps = DragAndDropProps & {
    isDroppable: boolean
    className?: string
    isDragging?: boolean
    isRoot?: boolean
    style?: CSSProperties
    // When 'reorder', render an insertion line above/below the row based on pointer position
    // and report which side was targeted. Defaults to 'onto' (ring highlight on the whole row).
    dropMode?: 'onto' | 'reorder'
    onPositionChange?: (id: string, position: TreeDropPosition) => void
}

export const TreeNodeDroppable = (props: DroppableProps): JSX.Element => {
    const { setNodeRef, isOver } = useDroppable({ id: props.id })
    const nodeRef = useRef<HTMLDivElement | null>(null)
    const [reorderSide, setReorderSide] = useState<'before' | 'after' | null>(null)

    const setRefs = (el: HTMLDivElement | null): void => {
        nodeRef.current = el
        setNodeRef(el)
    }

    const isReorder = props.dropMode === 'reorder' && props.isDroppable
    const onPositionChange = props.onPositionChange
    const propsId = props.id

    // While the user is hovering this row mid-drag, track the pointer at the document
    // level so we reliably know whether they're over the top or bottom half — React's
    // onPointerMove on the node can miss updates if the pointer barely moves or the
    // drag preview briefly covers the row.
    useEffect(() => {
        if (!isReorder || !isOver) {
            setReorderSide(null)
            return
        }
        // 2px deadband around the midpoint so hovering exactly on the line doesn't
        // flip-flop the indicator back and forth on every sub-pixel of movement.
        const DEADBAND = 2
        const updateFromClientY = (clientY: number): void => {
            if (!nodeRef.current) {
                return
            }
            const rect = nodeRef.current.getBoundingClientRect()
            const midY = rect.top + rect.height / 2
            if (Math.abs(clientY - midY) < DEADBAND) {
                return
            }
            const side: 'before' | 'after' = clientY < midY ? 'before' : 'after'
            setReorderSide((prev) => {
                if (prev !== side) {
                    onPositionChange?.(propsId, side)
                    return side
                }
                return prev
            })
        }
        const handleMove = (e: PointerEvent): void => updateFromClientY(e.clientY)
        document.addEventListener('pointermove', handleMove)
        return () => document.removeEventListener('pointermove', handleMove)
    }, [isReorder, isOver, onPositionChange, propsId])

    const showRing = props.isDroppable && isOver && !isReorder
    const showLineBefore = isReorder && isOver && reorderSide === 'before'
    const showLineAfter = isReorder && isOver && reorderSide === 'after'

    return (
        <div
            ref={setRefs}
            className={cn(
                'flex flex-col rounded relative z-2 ',
                // Keep the ring mode transition for existing consumers; skip it in reorder mode
                // so the insertion indicator appears/moves instantly and doesn't tween width.
                !isReorder && 'transition-all duration-150',
                props.className,
                // In reorder mode force full row width so the insertion line has a
                // consistent visible length across rows with different label widths.
                isReorder && 'w-full',
                showRing && 'ring-2 ring-inset ring-accent bg-accent-highlight-secondary',
                // If the item is a root item and it's dragging, make it take up the full height
                props.isRoot && props.isDragging && 'h-full'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={props.style}
        >
            {showLineBefore && (
                <div className="pointer-events-none absolute -top-px left-2 right-2 h-0.5 bg-accent z-10" />
            )}
            {props.children}
            {showLineAfter && (
                <div className="pointer-events-none absolute -bottom-px left-2 right-2 h-0.5 bg-accent z-10" />
            )}
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
