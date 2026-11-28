import './tree.css'

import { ChevronRightIcon } from 'lucide-react'
import * as React from 'react'

import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from './context-menu'
import { Highlight } from './highlight'
import { cn } from './lib/utils'

export interface TreeNode {
    id: string
    textValue: string
    children?: TreeNode[]
    /** True when the node has children that are not loaded yet; expanding it calls onLoadChildren. */
    hasChildren?: boolean
    section?: boolean
    disabledReason?: string
}

export interface TreeItemState {
    depth: number
    expanded: boolean
    selected: boolean
    focused: boolean
    hasChildren: boolean
    section: boolean
}

export interface TreeRef {
    focusItem: (id: string) => void
    scrollToItem: (id: string) => void
    focus: () => void
}

export interface TreeProps<T extends TreeNode> extends Omit<
    React.HTMLAttributes<HTMLDivElement>,
    'children' | 'onSelect' | 'defaultValue'
> {
    items: T[]
    expandedIds: string[]
    onExpandedIdsChange: (ids: string[], change: { id: string; expanded: boolean; node: T }) => void
    selectedId?: string | null
    onSelectedIdChange?: (id: string, node: T) => void
    /** Enter, and click on a leaf / double-click on a branch. Clicking a branch toggles it. */
    onAction?: (node: T) => void
    onLoadChildren?: (node: T) => void
    renderItem: (node: T, state: TreeItemState) => React.ReactNode
    renderContextMenu?: (node: T) => React.ReactNode
    getItemProps?: (node: T) => React.HTMLAttributes<HTMLDivElement> & { 'data-attr'?: string }
    virtualized?: boolean
    rowHeight?: number
    overscan?: number
    empty?: React.ReactNode
    'aria-label': string
}

interface FlatRow<T extends TreeNode> {
    node: T
    depth: number
    parentId: string | null
    posInSet: number
    setSize: number
    isBranch: boolean
    expanded: boolean
    /** First ancestor level that draws an indent guide: levels at or above the deepest section ancestor draw none. */
    guideFrom: number
}

const TYPEAHEAD_TIMEOUT_MS = 500

function isBranchNode(node: TreeNode): boolean {
    return !!node.hasChildren || (node.children?.length ?? 0) > 0
}

function flatten<T extends TreeNode>(items: T[], expanded: Set<string>): FlatRow<T>[] {
    const rows: FlatRow<T>[] = []
    const walk = (nodes: T[], depth: number, parentId: string | null, guideFrom: number): void => {
        nodes.forEach((node, index) => {
            const isBranch = isBranchNode(node)
            const isExpanded = isBranch && expanded.has(node.id)
            rows.push({
                node,
                depth,
                parentId,
                posInSet: index + 1,
                setSize: nodes.length,
                isBranch,
                expanded: isExpanded,
                guideFrom,
            })
            if (isExpanded && node.children) {
                walk(node.children as T[], depth + 1, node.id, node.section ? depth + 1 : guideFrom)
            }
        })
    }
    walk(items, 0, null, 0)
    return rows
}

function composeHandlers<E>(theirs: ((event: E) => void) | undefined, ours: (event: E) => void): (event: E) => void {
    return (event) => {
        theirs?.(event)
        ours(event)
    }
}

/** True when the event came from this element's own DOM subtree, not from a portal (a context menu) React bubbles through it. */
function isFromOwnSubtree(event: React.SyntheticEvent): boolean {
    return event.currentTarget instanceof Node && event.currentTarget.contains(event.target as Node)
}

function TreeInner<T extends TreeNode>(
    {
        items,
        expandedIds,
        onExpandedIdsChange,
        selectedId = null,
        onSelectedIdChange,
        onAction,
        onLoadChildren,
        renderItem,
        renderContextMenu,
        getItemProps,
        virtualized = false,
        rowHeight = 28,
        overscan = 12,
        empty,
        className,
        style,
        onKeyDown,
        onScroll,
        ...props
    }: TreeProps<T>,
    ref: React.ForwardedRef<TreeRef>
): React.ReactElement {
    const containerRef = React.useRef<HTMLDivElement>(null)
    const listRef = React.useRef<HTMLDivElement>(null)
    const getRowElement = React.useCallback((id: string): HTMLElement | undefined => {
        const rowNodes = containerRef.current?.querySelectorAll<HTMLElement>('[role="treeitem"]') ?? []
        return Array.from(rowNodes).find((element) => element.dataset.treeItemId === id)
    }, [])
    const pendingFocus = React.useRef<string | null>(null)
    const typeahead = React.useRef<{ buffer: string; timer: ReturnType<typeof setTimeout> | undefined }>({
        buffer: '',
        timer: undefined,
    })

    const expandedSet = React.useMemo(() => new Set(expandedIds), [expandedIds])
    const rows = React.useMemo(() => flatten(items, expandedSet), [items, expandedSet])
    const indexById = React.useMemo(() => {
        const map = new Map<string, number>()
        rows.forEach((row, index) => map.set(row.node.id, index))
        return map
    }, [rows])

    const [focusedIdState, setFocusedId] = React.useState<string | null>(null)
    // The roving tab stop: the last focused row while it is visible, else the selected row, else the first.
    const focusedId =
        focusedIdState !== null && indexById.has(focusedIdState)
            ? focusedIdState
            : selectedId !== null && indexById.has(selectedId)
              ? selectedId
              : (rows[0]?.node.id ?? null)
    const focusedIndex = focusedId !== null ? (indexById.get(focusedId) ?? -1) : -1

    const [range, setRange] = React.useState<{ start: number; end: number }>({ start: 0, end: overscan })

    const measureRange = React.useCallback(() => {
        const container = containerRef.current
        if (!virtualized || !container) {
            return
        }
        const listOffset = listRef.current?.offsetTop ?? 0
        const scrollTop = Math.max(0, container.scrollTop - listOffset)
        const viewport = container.clientHeight
        const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan)
        const end = Math.min(rows.length, Math.ceil((scrollTop + viewport) / rowHeight) + overscan)
        setRange((current) => (current.start === start && current.end === end ? current : { start, end }))
    }, [virtualized, rowHeight, overscan, rows.length])

    React.useLayoutEffect(() => {
        measureRange()
    }, [measureRange])

    React.useEffect(() => {
        const container = containerRef.current
        if (!virtualized || !container || typeof ResizeObserver === 'undefined') {
            return
        }
        const observer = new ResizeObserver(() => measureRange())
        observer.observe(container)
        return () => observer.disconnect()
    }, [virtualized, measureRange])

    // Indices to render: everything, or the window plus the focused row so roving focus is never lost.
    const renderedIndices = React.useMemo(() => {
        if (!virtualized) {
            return rows.map((_, index) => index)
        }
        const end = Math.min(range.end, rows.length)
        const indices: number[] = []
        if (focusedIndex >= 0 && focusedIndex < range.start) {
            indices.push(focusedIndex)
        }
        for (let index = range.start; index < end; index++) {
            indices.push(index)
        }
        if (focusedIndex >= end) {
            indices.push(focusedIndex)
        }
        return indices
    }, [virtualized, rows, range, focusedIndex])

    React.useLayoutEffect(() => {
        const id = pendingFocus.current
        if (id === null) {
            return
        }
        const element = getRowElement(id)
        if (element) {
            pendingFocus.current = null
            element.focus({ preventScroll: true })
            element.scrollIntoView?.({ block: 'nearest' })
        }
    })

    const moveFocus = React.useCallback(
        (id: string) => {
            pendingFocus.current = id
            setFocusedId(id)
            // Already focused-by-state rows don't re-render, so focus them right away.
            const element = getRowElement(id)
            if (element && document.activeElement !== element) {
                element.focus({ preventScroll: true })
                element.scrollIntoView?.({ block: 'nearest' })
                pendingFocus.current = null
            }
        },
        [getRowElement]
    )

    const scrollToIndex = React.useCallback(
        (index: number) => {
            const container = containerRef.current
            const id = rows[index]?.node.id
            const element = id !== undefined ? getRowElement(id) : undefined
            if (element?.scrollIntoView) {
                element.scrollIntoView({ block: 'nearest' })
            } else if (container) {
                const listOffset = listRef.current?.offsetTop ?? 0
                container.scrollTop = listOffset + index * rowHeight - (container.clientHeight - rowHeight) / 2
            }
        },
        [rows, rowHeight, getRowElement]
    )

    React.useImperativeHandle(
        ref,
        () => ({
            focusItem: (id) => {
                if (indexById.has(id)) {
                    const index = indexById.get(id) as number
                    scrollToIndex(index)
                    moveFocus(id)
                }
            },
            scrollToItem: (id) => {
                const index = indexById.get(id)
                if (index !== undefined) {
                    scrollToIndex(index)
                }
            },
            focus: () => {
                if (focusedId !== null) {
                    moveFocus(focusedId)
                }
            },
        }),
        [indexById, scrollToIndex, moveFocus, focusedId]
    )

    const setExpanded = React.useCallback(
        (row: FlatRow<T>, expanded: boolean, currentIds: string[] = expandedIds): string[] => {
            const { node } = row
            const has = currentIds.includes(node.id)
            if (has === expanded) {
                return currentIds
            }
            const nextIds = expanded ? [...currentIds, node.id] : currentIds.filter((id) => id !== node.id)
            onExpandedIdsChange(nextIds, { id: node.id, expanded, node })
            if (expanded && node.hasChildren && node.children === undefined) {
                onLoadChildren?.(node)
            }
            return nextIds
        },
        [expandedIds, onExpandedIdsChange, onLoadChildren]
    )

    const select = React.useCallback(
        (row: FlatRow<T>) => {
            if (row.node.disabledReason) {
                return
            }
            onSelectedIdChange?.(row.node.id, row.node)
        },
        [onSelectedIdChange]
    )

    const runAction = React.useCallback(
        (row: FlatRow<T>) => {
            if (row.node.disabledReason) {
                return
            }
            onAction?.(row.node)
        },
        [onAction]
    )

    const handleTypeahead = (key: string, fromIndex: number): void => {
        const state = typeahead.current
        clearTimeout(state.timer)
        state.buffer += key.toLowerCase()
        state.timer = setTimeout(() => {
            state.buffer = ''
        }, TYPEAHEAD_TIMEOUT_MS)
        // A fresh single character moves past the current row, so repeating it cycles through matches.
        const start = state.buffer.length === 1 ? fromIndex + 1 : fromIndex
        for (let offset = 0; offset < rows.length; offset++) {
            const index = (start + offset) % rows.length
            if (rows[index].node.textValue.toLowerCase().startsWith(state.buffer)) {
                moveFocus(rows[index].node.id)
                return
            }
        }
    }

    React.useEffect(() => () => clearTimeout(typeahead.current.timer), [])

    const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>): void => {
        onKeyDown?.(event)
        const target = event.target as HTMLElement
        // Only keys pressed on a row of this tree: not a control inside a row, not a portaled menu.
        if (
            event.defaultPrevented ||
            focusedIndex < 0 ||
            target.getAttribute('role') !== 'treeitem' ||
            !event.currentTarget.contains(target)
        ) {
            return
        }
        const row = rows[focusedIndex]
        const go = (index: number): void => {
            const next = rows[Math.max(0, Math.min(rows.length - 1, index))]
            if (next) {
                moveFocus(next.node.id)
            }
        }
        let handled = true
        switch (event.key) {
            case 'ArrowDown':
                go(focusedIndex + 1)
                break
            case 'ArrowUp':
                go(focusedIndex - 1)
                break
            case 'Home':
                go(0)
                break
            case 'End':
                go(rows.length - 1)
                break
            case 'ArrowRight':
                if (row.isBranch && !row.expanded) {
                    setExpanded(row, true)
                } else if (row.expanded && rows[focusedIndex + 1]?.parentId === row.node.id) {
                    go(focusedIndex + 1)
                }
                break
            case 'ArrowLeft':
                if (row.expanded) {
                    setExpanded(row, false)
                } else if (row.parentId !== null) {
                    moveFocus(row.parentId)
                }
                break
            case 'Enter':
                select(row)
                runAction(row)
                break
            case ' ':
                select(row)
                break
            case '*': {
                let ids = expandedIds
                rows.forEach((sibling) => {
                    if (sibling.parentId === row.parentId && sibling.isBranch && !sibling.expanded) {
                        ids = setExpanded(sibling, true, ids)
                    }
                })
                break
            }
            default:
                if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
                    handleTypeahead(event.key, focusedIndex)
                } else {
                    handled = false
                }
        }
        if (handled) {
            event.preventDefault()
            event.stopPropagation()
        }
    }

    const handleScroll = (event: React.UIEvent<HTMLDivElement>): void => {
        onScroll?.(event)
        measureRange()
    }

    if (items.length === 0) {
        return (
            <div
                data-quill
                data-slot="tree"
                data-empty=""
                className={cn('quill-tree', className)}
                style={style}
                {...props}
            >
                {empty}
            </div>
        )
    }

    const renderRow = (index: number): React.ReactNode => {
        const row = rows[index]
        const { node, depth } = row
        const selected = selectedId === node.id
        const focused = focusedId === node.id
        const state: TreeItemState = {
            depth,
            expanded: row.expanded,
            selected,
            focused,
            hasChildren: row.isBranch,
            section: !!node.section,
        }
        const extra = getItemProps?.(node) ?? {}
        const loading = row.expanded && !!node.hasChildren && node.children === undefined
        const rowProps: React.HTMLAttributes<HTMLDivElement> & Record<`data-${string}`, unknown> = {
            ...extra,
            role: 'treeitem',
            tabIndex: focused ? 0 : -1,
            'aria-level': depth + 1,
            'aria-posinset': row.posInSet,
            'aria-setsize': row.setSize,
            'aria-expanded': row.isBranch ? row.expanded : undefined,
            'aria-selected': selected,
            'aria-disabled': node.disabledReason ? true : undefined,
            'aria-busy': loading || undefined,
            title: node.disabledReason ?? extra.title,
            'data-slot': 'tree-item',
            'data-tree-item-id': node.id,
            'data-section': node.section ? '' : undefined,
            'data-focused': focused ? '' : undefined,
            className: cn('quill-tree__item group/tree-item', extra.className),
            style: {
                ...extra.style,
                '--quill-tree-depth': depth,
                '--quill-tree-guide-from': row.guideFrom,
            } as React.CSSProperties,
            onFocus: composeHandlers(extra.onFocus, (event) => {
                if (event.target === event.currentTarget) {
                    setFocusedId(node.id)
                }
            }),
            onClick: composeHandlers(extra.onClick, (event) => {
                if (!isFromOwnSubtree(event)) {
                    return
                }
                setFocusedId(node.id)
                select(row)
                if (row.isBranch) {
                    setExpanded(row, !row.expanded)
                } else {
                    runAction(row)
                }
            }),
            onDoubleClick: composeHandlers(extra.onDoubleClick, (event) => {
                if (isFromOwnSubtree(event) && row.isBranch) {
                    runAction(row)
                }
            }),
        }
        const content = (
            <>
                <span data-slot="tree-item-chevron" className="quill-tree__chevron" aria-hidden="true">
                    {row.isBranch && <ChevronRightIcon />}
                </span>
                {renderItem(node, state)}
            </>
        )
        const menu = renderContextMenu?.(node)
        if (menu !== null && menu !== undefined && menu !== false) {
            return (
                <ContextMenu key={node.id}>
                    <ContextMenuTrigger {...rowProps}>{content}</ContextMenuTrigger>
                    <ContextMenuContent>{menu}</ContextMenuContent>
                </ContextMenu>
            )
        }
        return (
            <div key={node.id} {...rowProps}>
                {content}
            </div>
        )
    }

    const children: React.ReactNode[] = []
    let previous = -1
    for (const index of renderedIndices) {
        if (index > previous + 1) {
            children.push(
                <div
                    key={`spacer-${previous + 1}`}
                    aria-hidden="true"
                    data-slot="tree-spacer"
                    style={{ height: (index - previous - 1) * rowHeight }}
                />
            )
        }
        children.push(renderRow(index))
        previous = index
    }
    if (virtualized && previous < rows.length - 1) {
        children.push(
            <div
                key="spacer-end"
                aria-hidden="true"
                data-slot="tree-spacer"
                style={{ height: (rows.length - previous - 1) * rowHeight }}
            />
        )
    }

    return (
        <div
            ref={containerRef}
            data-quill
            data-slot="tree"
            role="tree"
            className={cn('quill-tree scroll-mask-y-4 scroll-py-4', className)}
            style={{ ...style, '--quill-tree-row-height': `${rowHeight}px` } as React.CSSProperties}
            onKeyDown={handleKeyDown}
            onScroll={handleScroll}
            {...props}
        >
            {/* role="none": the rows' tree is their aria-level, not this wrapper. */}
            <div ref={listRef} role="none" className="quill-tree__list">
                {children}
            </div>
        </div>
    )
}

// The cast restores the node generic, because forwardRef cannot carry a generic signature.
const Tree = React.forwardRef(TreeInner) as <T extends TreeNode>(
    props: TreeProps<T> & { ref?: React.Ref<TreeRef> }
) => React.ReactElement

const TreeItemIcon = React.forwardRef<HTMLSpanElement, React.ComponentProps<'span'>>(function TreeItemIcon(
    { className, ...props },
    ref
) {
    return <span ref={ref} data-slot="tree-item-icon" className={cn('quill-tree__icon', className)} {...props} />
})

function highlightText(text: string, query: string): React.ReactNode {
    const needle = query.trim().toLowerCase()
    if (!needle) {
        return text
    }
    const haystack = text.toLowerCase()
    const parts: React.ReactNode[] = []
    let cursor = 0
    let match = haystack.indexOf(needle)
    while (match !== -1) {
        if (match > cursor) {
            parts.push(text.slice(cursor, match))
        }
        parts.push(<Highlight key={match}>{text.slice(match, match + needle.length)}</Highlight>)
        cursor = match + needle.length
        match = haystack.indexOf(needle, cursor)
    }
    if (cursor < text.length) {
        parts.push(text.slice(cursor))
    }
    return parts
}

interface TreeItemLabelProps extends React.ComponentProps<'span'> {
    /** Wraps each case-insensitive match of this text in a highlight. Applies when children is a string. */
    highlight?: string
}

const TreeItemLabel = React.forwardRef<HTMLSpanElement, TreeItemLabelProps>(function TreeItemLabel(
    { className, highlight, children, ...props },
    ref
) {
    return (
        <span ref={ref} data-slot="tree-item-label" className={cn('quill-tree__label', className)} {...props}>
            {typeof children === 'string' && highlight ? highlightText(children, highlight) : children}
        </span>
    )
})

const TreeItemMeta = React.forwardRef<HTMLSpanElement, React.ComponentProps<'span'>>(function TreeItemMeta(
    { className, ...props },
    ref
) {
    return <span ref={ref} data-slot="tree-item-meta" className={cn('quill-tree__meta', className)} {...props} />
})

const stopPropagation = (event: React.SyntheticEvent): void => event.stopPropagation()

/**
 * Trailing row actions, shown while the row is hovered or focused and while a popup they opened is open.
 * Clicks, presses and keys inside stay here, so a menu trigger doesn't toggle, select or move the row.
 */
const TreeItemActions = React.forwardRef<HTMLSpanElement, React.ComponentProps<'span'>>(function TreeItemActions(
    { className, onClick, onKeyDown, onPointerDown, onDoubleClick, ...props },
    ref
) {
    return (
        <span
            ref={ref}
            data-slot="tree-item-actions"
            className={cn('quill-tree__actions', className)}
            onClick={composeHandlers(onClick, stopPropagation)}
            onDoubleClick={composeHandlers(onDoubleClick, stopPropagation)}
            onKeyDown={composeHandlers(onKeyDown, stopPropagation)}
            onPointerDown={composeHandlers(onPointerDown, stopPropagation)}
            {...props}
        />
    )
})

export { Tree, TreeItemIcon, TreeItemLabel, TreeItemMeta, TreeItemActions }
export type { TreeItemLabelProps }
