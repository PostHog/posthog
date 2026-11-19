import type { Meta, StoryObj } from '@storybook/react'
import { Columns3Icon, GripVerticalIcon } from 'lucide-react'
import * as React from 'react'

import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from '@posthog/quill-primitives'

// A mock, not an export yet: a menu of checkbox rows the user can also reorder,
// by dragging a row's grip or with Alt+ArrowUp / Alt+ArrowDown on the focused row.
const meta = {
    title: 'Components/SortableMenu (mock)',
    tags: ['autodocs'],
} satisfies Meta

export default meta
type Story = StoryObj<typeof meta>

interface Column {
    key: string
    label: string
    pinned?: boolean
}

const COLUMNS: Column[] = [
    { key: 'ticket', label: 'Ticket', pinned: true },
    { key: 'person', label: 'Person' },
    { key: 'last_message', label: 'Last message' },
    { key: 'status', label: 'Status' },
    { key: 'priority', label: 'Priority' },
    { key: 'sla', label: 'SLA' },
    { key: 'assignee', label: 'Assignee' },
    { key: 'channel', label: 'Channel' },
    { key: 'tags', label: 'Tags' },
    { key: 'created', label: 'Created' },
    { key: 'updated', label: 'Updated' },
]
const DEFAULT_ORDER = COLUMNS.map((column) => column.key)
const LABELS = Object.fromEntries(COLUMNS.map((column) => [column.key, column.label]))

function move<T>(list: T[], from: number, to: number): T[] {
    const next = [...list]
    const [item] = next.splice(from, 1)
    next.splice(to, 0, item)
    return next
}

function useColumnsState(): {
    order: string[]
    shown: Set<string>
    widthsChanged: boolean
    setOrder: (order: string[]) => void
    toggle: (key: string) => void
    resetColumns: () => void
    resetWidths: () => void
} {
    const [order, setOrder] = React.useState(DEFAULT_ORDER)
    const [shown, setShown] = React.useState(() => new Set(DEFAULT_ORDER))
    const [widthsChanged, setWidthsChanged] = React.useState(true)
    return {
        order,
        shown,
        widthsChanged,
        setOrder,
        toggle: (key) =>
            setShown((current) => {
                const next = new Set(current)
                next.has(key) ? next.delete(key) : next.add(key)
                return next
            }),
        resetColumns: () => {
            setOrder(DEFAULT_ORDER)
            setShown(new Set(DEFAULT_ORDER))
        },
        resetWidths: () => setWidthsChanged(false),
    }
}

/** The checkbox rows, reorderable. A pinned row stays first and has no grip. */
function SortableColumnItems({
    order,
    shown,
    onOrderChange,
    onToggle,
}: {
    order: string[]
    shown: Set<string>
    onOrderChange: (order: string[]) => void
    onToggle: (key: string) => void
}): React.ReactElement {
    const listRef = React.useRef<HTMLDivElement>(null)
    const [dragging, setDragging] = React.useState<string | null>(null)
    const pinnedCount = order.filter((key) => COLUMNS.find((c) => c.key === key)?.pinned).length

    const moveTo = (key: string, target: number): void => {
        const from = order.indexOf(key)
        const to = Math.max(pinnedCount, Math.min(order.length - 1, target))
        if (from !== to) {
            onOrderChange(move(order, from, to))
        }
    }

    // The target index is the row whose middle the pointer has passed.
    const onPointerMove = (event: React.PointerEvent): void => {
        if (!dragging || !listRef.current) {
            return
        }
        const rows = Array.from(listRef.current.querySelectorAll<HTMLElement>('[data-sortable-key]'))
        let target = rows.length - 1
        for (let index = 0; index < rows.length; index++) {
            const rect = rows[index].getBoundingClientRect()
            if (event.clientY < rect.top + rect.height / 2) {
                target = index
                break
            }
        }
        moveTo(dragging, target)
    }

    return (
        <div ref={listRef} className="flex flex-col">
            {order.map((key) => {
                const pinned = COLUMNS.find((c) => c.key === key)?.pinned
                return (
                    <DropdownMenuCheckboxItem
                        key={key}
                        data-sortable-key={key}
                        checked={pinned || shown.has(key)}
                        closeOnClick={false}
                        disabledReason={pinned ? 'This column identifies the ticket' : undefined}
                        onCheckedChange={() => onToggle(key)}
                        className={dragging === key ? 'bg-fill-selected' : undefined}
                        onKeyDown={(event) => {
                            if (pinned || !event.altKey || (event.key !== 'ArrowUp' && event.key !== 'ArrowDown')) {
                                return
                            }
                            event.preventDefault()
                            event.preventBaseUIHandler()
                            const row = event.currentTarget
                            moveTo(key, order.indexOf(key) + (event.key === 'ArrowUp' ? -1 : 1))
                            requestAnimationFrame(() => row.focus())
                        }}
                    >
                        {LABELS[key]}
                        {!pinned && (
                            <span
                                aria-hidden
                                data-sortable-handle
                                // The row ignores pointer events on svgs, so the span is the handle.
                                className="ms-auto -me-1 flex cursor-grab touch-none items-center text-muted-foreground/60 hover:text-foreground active:cursor-grabbing"
                                onPointerDown={(event) => {
                                    event.preventDefault()
                                    event.stopPropagation()
                                    event.currentTarget.setPointerCapture(event.pointerId)
                                    setDragging(key)
                                }}
                                onPointerMove={onPointerMove}
                                onPointerUp={(event) => {
                                    event.currentTarget.releasePointerCapture(event.pointerId)
                                    setDragging(null)
                                }}
                                onClick={(event) => {
                                    // A drag ends in a click on the row; it must not toggle the column.
                                    event.preventDefault()
                                    event.stopPropagation()
                                }}
                            >
                                <GripVerticalIcon className="size-3.5" />
                            </span>
                        )}
                    </DropdownMenuCheckboxItem>
                )
            })}
        </div>
    )
}

// Its own dropdown beside the filter menu: the columns, then the two resets.
export const ColumnsMenu: Story = {
    render: function Render() {
        const state = useColumnsState()
        const columnsAreDefault =
            state.order.every((key, index) => key === DEFAULT_ORDER[index]) && state.shown.size === DEFAULT_ORDER.length
        return (
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button variant="outline" size="sm">
                            <Columns3Icon />
                            Columns
                        </Button>
                    }
                />
                <DropdownMenuContent align="start" className="min-w-56">
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>Drag to reorder</DropdownMenuLabel>
                        <SortableColumnItems
                            order={state.order}
                            shown={state.shown}
                            onOrderChange={state.setOrder}
                            onToggle={state.toggle}
                        />
                    </DropdownMenuGroup>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                        closeOnClick={false}
                        disabledReason={columnsAreDefault ? 'Columns are already at their default' : undefined}
                        onClick={state.resetColumns}
                    >
                        Reset columns
                    </DropdownMenuItem>
                    <DropdownMenuItem
                        closeOnClick={false}
                        disabledReason={state.widthsChanged ? undefined : 'No column has been resized'}
                        onClick={state.resetWidths}
                    >
                        Reset column widths
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
        )
    },
}

// The same rows one level down, to check a drag survives a submenu's hover handling.
export const InSubMenu: Story = {
    render: function Render() {
        const state = useColumnsState()
        return (
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button variant="outline" size="sm">
                            <Columns3Icon />
                            View
                        </Button>
                    }
                />
                <DropdownMenuContent align="start" className="min-w-56">
                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger>
                            Columns
                            <span className="ms-auto text-muted-foreground">
                                {state.shown.size} of {DEFAULT_ORDER.length}
                            </span>
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent className="min-w-56">
                            <SortableColumnItems
                                order={state.order}
                                shown={state.shown}
                                onOrderChange={state.setOrder}
                                onToggle={state.toggle}
                            />
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem closeOnClick={false} onClick={state.resetColumns}>
                        Reset columns
                    </DropdownMenuItem>
                    <DropdownMenuItem closeOnClick={false} onClick={state.resetWidths}>
                        Reset column widths
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
        )
    },
}
