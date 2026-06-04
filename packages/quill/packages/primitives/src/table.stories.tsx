import type { Meta, StoryObj } from '@storybook/react'
import { ChevronsUpDown, MoreHorizontal } from 'lucide-react'
import * as React from 'react'

import { Badge } from './badge'
import { Button } from './button'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from './dropdown-menu'
import { ItemContent, ItemDescription, ItemTitle } from './item'
import { Table, TableBody, TableCaption, TableCell, TableFooter, TableHead, TableHeader, TableRow } from './table'

const meta = {
    title: 'Primitives/Table',
    component: Table,
    tags: ['autodocs'],
} satisfies Meta<typeof Table>

export default meta
type Story = StoryObj<typeof meta>

// Maps a status string to a semantic Badge variant, shared across the Status
// columns below. Positive states (Paid/Active) read success, in-flight states
// (Pending/Invited) read warning, everything else (Unpaid/Refunded) destructive.
function StatusBadge({ status }: { status: string }): React.ReactElement {
    const variant =
        status === 'Paid' || status === 'Active'
            ? 'success'
            : status === 'Pending' || status === 'Invited'
              ? 'warning'
              : 'destructive'
    return <Badge variant={variant}>{status}</Badge>
}

const invoices = [
    { invoice: 'INV001', status: 'Paid', method: 'Credit Card', amount: '$250.00' },
    { invoice: 'INV002', status: 'Pending', method: 'PayPal', amount: '$150.00' },
    { invoice: 'INV003', status: 'Unpaid', method: 'Bank Transfer', amount: '$350.00' },
    { invoice: 'INV004', status: 'Paid', method: 'Credit Card', amount: '$450.00' },
    { invoice: 'INV005', status: 'Paid', method: 'PayPal', amount: '$550.00' },
]

export const Default: Story = {
    render: () => (
        <Table className="max-w-2xl">
            <TableCaption>A list of your recent invoices.</TableCaption>
            <TableHeader>
                <TableRow>
                    <TableHead>Invoice</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Method</TableHead>
                    <TableHead className="text-right">Amount</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {invoices.map((row) => (
                    <TableRow key={row.invoice}>
                        <TableCell className="font-medium">{row.invoice}</TableCell>
                        <TableCell>
                            <StatusBadge status={row.status} />
                        </TableCell>
                        <TableCell>{row.method}</TableCell>
                        <TableCell className="text-right">{row.amount}</TableCell>
                    </TableRow>
                ))}
            </TableBody>
            <TableFooter>
                <TableRow>
                    <TableCell colSpan={3}>Total</TableCell>
                    <TableCell className="text-right">$1,750.00</TableCell>
                </TableRow>
            </TableFooter>
        </Table>
    ),
} satisfies Story

// Intra-cell alignment via the `align` (horizontal) and `valign` (vertical)
// props on TableHead / TableCell — header and body cells share the same axis so
// numeric columns line up. The multi-line cell shows `valign="top"`.
export const Alignment: Story = {
    render: () => (
        <Table className="max-w-2xl">
            <TableHeader>
                <TableRow>
                    <TableHead>Invoice</TableHead>
                    <TableHead align="center">Status</TableHead>
                    <TableHead valign="top">Note</TableHead>
                    <TableHead align="right">Amount</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {invoices.map((row, i) => (
                    <TableRow key={row.invoice}>
                        <TableCell className="font-medium">{row.invoice}</TableCell>
                        <TableCell align="center">
                            <StatusBadge status={row.status} />
                        </TableCell>
                        <TableCell valign="top">
                            {i === 0 ? 'Top-aligned cell next to a taller, wrapping note column.' : row.method}
                        </TableCell>
                        <TableCell align="right" className="tabular-nums">
                            {row.amount}
                        </TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    ),
} satisfies Story

// All three CellLayout options in one table: `expand` makes the Task column
// soak up the width (its wrapping description makes rows tall), `valign="top"`
// keeps the short Status/Points cells aligned to that first line instead of
// floating to the middle, `align="center"` centers the status badge, and
// `align="right"` right-aligns the numeric points.
const tasks = [
    {
        title: 'expand',
        detail: 'This column sets `expand`, so it absorbs the table’s leftover width while Status and Points stay snug around their own content.',
        status: 'Active',
        points: 8,
    },
    {
        title: 'valign="top"',
        detail: 'Every cell in the row is top-aligned. This text wraps onto several lines to make the row tall, yet the badge and number stay pinned to this first line instead of floating to the middle.',
        status: 'Pending',
        points: 3,
    },
    {
        title: 'align',
        detail: 'Status uses `align="center"` and Points uses `align="right"` — the badge sits centered in its column and the number is pushed to the right edge.',
        status: 'Unpaid',
        points: 13,
    },
]

export const CellLayout: Story = {
    render: () => (
        <Table fullWidth className="rounded-md border border-[var(--border)]">
            <TableHeader>
                <TableRow>
                    <TableHead expand>Task</TableHead>
                    <TableHead align="center">Status</TableHead>
                    <TableHead align="right">Points</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {tasks.map((row) => (
                    <TableRow key={row.title}>
                        <TableCell expand valign="top">
                            <ItemContent className="min-w-0 gap-0.5">
                                <ItemTitle className="truncate">{row.title}</ItemTitle>
                                <ItemDescription>{row.detail}</ItemDescription>
                            </ItemContent>
                        </TableCell>
                        <TableCell align="center" valign="top">
                            <StatusBadge status={row.status} />
                        </TableCell>
                        <TableCell align="right" valign="top" className="tabular-nums">
                            {row.points}
                        </TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    ),
} satisfies Story

// Full-width table: `fullWidth` stretches it to the container, and `expand` on
// the Name column makes that column soak up the slack while the others stay
// snug around their content. Long names truncate inside the expanding cell.
const members = [
    { name: 'Ava Thompson', email: 'ava@example.com', role: 'Admin', status: 'Active', seats: 5 },
    { name: 'Benjamin Carter', email: 'ben@example.com', role: 'Member', status: 'Active', seats: 1 },
    { name: 'Cara Mendoza-Whitfield', email: 'cara@example.com', role: 'Member', status: 'Invited', seats: 2 },
    { name: 'Dan Okafor', email: 'dan@example.com', role: 'Billing', status: 'Active', seats: 8 },
]

export const FullWidth: Story = {
    render: () => (
        <Table fullWidth className="rounded-md border border-[var(--border)]">
            <TableHeader>
                <TableRow>
                    <TableHead expand>Member</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead align="center">Status</TableHead>
                    <TableHead align="right">Seats</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {members.map((row) => (
                    <TableRow key={row.email}>
                        <TableCell expand>
                            <ItemContent className="min-w-0">
                                <ItemTitle className="truncate">{row.name}</ItemTitle>
                                <ItemDescription className="truncate">{row.email}</ItemDescription>
                            </ItemContent>
                        </TableCell>
                        <TableCell className="whitespace-nowrap">{row.role}</TableCell>
                        <TableCell align="center">
                            <StatusBadge status={row.status} />
                        </TableCell>
                        <TableCell align="right" className="tabular-nums">
                            {row.seats}
                        </TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    ),
} satisfies Story

export const Selectable: Story = {
    render: () => (
        <Table className="max-w-2xl">
            <TableHeader>
                <TableRow>
                    <TableHead>Invoice</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Amount</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {invoices.map((row, i) => (
                    <TableRow key={row.invoice} data-state={i === 1 ? 'selected' : undefined}>
                        <TableCell className="font-medium">{row.invoice}</TableCell>
                        <TableCell>
                            <StatusBadge status={row.status} />
                        </TableCell>
                        <TableCell className="text-right">{row.amount}</TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    ),
} satisfies Story

const manyRows = Array.from({ length: 40 }, (_, i) => ({
    id: `USR-${String(i + 1).padStart(3, '0')}`,
    name: `Person ${i + 1}`,
    email: `person${i + 1}@example.com`,
    role: i % 3 === 0 ? 'Admin' : 'Member',
    status: i % 4 === 0 ? 'Invited' : 'Active',
}))

export const StickyHeader: Story = {
    render: () => (
        <Table stickyHeader className="h-72 max-w-2xl rounded-md border border-[var(--border)]">
            <TableHeader>
                <TableRow>
                    <TableHead>ID</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead>Role</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {manyRows.map((row) => (
                    <TableRow key={row.id}>
                        <TableCell className="font-medium">{row.id}</TableCell>
                        <TableCell>{row.name}</TableCell>
                        <TableCell>{row.email}</TableCell>
                        <TableCell>{row.role}</TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    ),
} satisfies Story

const wideColumns = [
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
]

export const StickyColumn: Story = {
    render: () => (
        <Table className="max-w-xl rounded-md border border-[var(--border)]">
            <TableHeader>
                <TableRow>
                    <TableHead sticky="left">Region</TableHead>
                    {wideColumns.map((q) => (
                        <TableHead key={q} className="text-right whitespace-nowrap">
                            {q}
                        </TableHead>
                    ))}
                </TableRow>
            </TableHeader>
            <TableBody>
                {['North America', 'Europe', 'Asia Pacific', 'Latin America'].map((region, r) => (
                    <TableRow key={region}>
                        <TableCell sticky="left" className="font-medium whitespace-nowrap">
                            {region}
                        </TableCell>
                        {wideColumns.map((q, c) => (
                            <TableCell key={q} className="text-right">
                                ${(r + 1) * (c + 1) * 1000}
                            </TableCell>
                        ))}
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    ),
} satisfies Story

export const StickyHeaderAndFirstColumn: Story = {
    render: () => (
        <Table stickyHeader className="h-72 max-w-xl rounded-md border border-[var(--border)]">
            <TableHeader>
                <TableRow>
                    <TableHead sticky="left">User</TableHead>
                    {wideColumns.map((q) => (
                        <TableHead key={q} className="text-right whitespace-nowrap">
                            {q}
                        </TableHead>
                    ))}
                </TableRow>
            </TableHeader>
            <TableBody>
                {manyRows.map((row) => (
                    <TableRow key={row.id}>
                        <TableCell sticky="left" className="font-medium whitespace-nowrap">
                            {row.name}
                        </TableCell>
                        {wideColumns.map((q, c) => (
                            <TableCell key={q} className="text-right">
                                {(c + 1) * 7}
                            </TableCell>
                        ))}
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    ),
} satisfies Story

export const StickyHeaderAndSecondColumn: Story = {
    render: () => (
        <Table stickyHeader className="h-72 max-w-xl rounded-md border border-[var(--border)]">
            <TableHeader>
                <TableRow>
                    <TableHead className="whitespace-nowrap">ID</TableHead>
                    <TableHead sticky="left" className="whitespace-nowrap">
                        User
                    </TableHead>
                    {wideColumns.map((q) => (
                        <TableHead key={q} className="text-right whitespace-nowrap">
                            {q}
                        </TableHead>
                    ))}
                </TableRow>
            </TableHeader>
            <TableBody>
                {manyRows.map((row) => (
                    <TableRow key={row.id}>
                        <TableCell className="whitespace-nowrap">{row.id}</TableCell>
                        <TableCell sticky="left" className="font-medium whitespace-nowrap">
                            {row.name}
                        </TableCell>
                        {wideColumns.map((q, c) => (
                            <TableCell key={q} className="text-right">
                                {(c + 1) * 7}
                            </TableCell>
                        ))}
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    ),
} satisfies Story

// Tall table with no internal scroll — the page scrolls, and the header sticks
// to the document. `stickyHeader="page"` drops the wrappers' scroll container so
// stickiness escapes to the window.
const pageRows = Array.from({ length: 60 }, (_, i) => ({
    id: `ORD-${String(i + 1).padStart(4, '0')}`,
    customer: `Customer ${i + 1}`,
    total: `$${((i + 1) * 37).toLocaleString()}`,
    status: ['Paid', 'Pending', 'Refunded'][i % 3],
}))

export const PageStickyHeader: Story = {
    render: () => (
        <div className="max-w-2xl">
            <p className="mb-4 text-sm text-[var(--muted-foreground)]">
                Scroll the page — the header sticks to the window once it reaches the top.
            </p>
            <Table stickyHeader="page" className="rounded-md border border-[var(--border)]">
                <TableHeader>
                    <TableRow>
                        <TableHead>Order</TableHead>
                        <TableHead>Customer</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead className="text-right">Total</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {pageRows.map((row) => (
                        <TableRow key={row.id}>
                            <TableCell className="font-medium">{row.id}</TableCell>
                            <TableCell>{row.customer}</TableCell>
                            <TableCell>
                                <StatusBadge status={row.status} />
                            </TableCell>
                            <TableCell className="text-right">{row.total}</TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </div>
    ),
} satisfies Story

// Any column can be frozen, not just the first. Here the 3rd column (Status)
// is sticky="left"; scrolling right slides the Order/Customer columns under it.
export const StickyNonFirstColumn: Story = {
    render: () => (
        <Table className="max-w-xl rounded-md border border-[var(--border)]">
            <TableHeader>
                <TableRow>
                    <TableHead className="whitespace-nowrap">Order</TableHead>
                    <TableHead className="whitespace-nowrap">Customer</TableHead>
                    <TableHead sticky="left" className="whitespace-nowrap">
                        Status
                    </TableHead>
                    {wideColumns.map((q) => (
                        <TableHead key={q} className="text-right whitespace-nowrap">
                            {q}
                        </TableHead>
                    ))}
                </TableRow>
            </TableHeader>
            <TableBody>
                {pageRows.slice(0, 8).map((row, r) => (
                    <TableRow key={row.id}>
                        <TableCell className="font-medium whitespace-nowrap">{row.id}</TableCell>
                        <TableCell className="whitespace-nowrap">{row.customer}</TableCell>
                        <TableCell sticky="left" className="whitespace-nowrap">
                            <StatusBadge status={row.status} />
                        </TableCell>
                        {wideColumns.map((q, c) => (
                            <TableCell key={q} className="text-right">
                                ${(r + 1) * (c + 1) * 100}
                            </TableCell>
                        ))}
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    ),
} satisfies Story

// Interactive headers: the whole label is a quill Button (label + sort
// icon) with normal button hover — the seam for sorting, column menus, etc. The
// button aligns with plain headers and doesn't shift layout; the non-interactive
// "#" header stays plain text.
export const InteractiveHeaders: Story = {
    render: () => (
        <Table className="max-w-2xl rounded-md border border-[var(--border)]">
            <TableHeader>
                <TableRow>
                    <TableHead className="w-10">#</TableHead>
                    {(['Name', 'Email', 'Role'] as const).map((label) => (
                        <TableHead key={label}>
                            <Button size="sm" className="gap-1.5" aria-label={`Sort by ${label}`}>
                                {label}
                                <ChevronsUpDown className="size-2.5" />
                            </Button>
                        </TableHead>
                    ))}
                </TableRow>
            </TableHeader>
            <TableBody>
                {manyRows.slice(0, 6).map((row, i) => (
                    <TableRow key={row.id}>
                        <TableCell className="text-[var(--muted-foreground)]">{i + 1}</TableCell>
                        <TableCell className="font-medium">{row.name}</TableCell>
                        <TableCell>{row.email}</TableCell>
                        <TableCell>{row.role}</TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    ),
} satisfies Story

// Shared dummy actions menu — an ellipsis Button that opens a quill
// DropdownMenu. Used by both the cell- and row-action stories.
function ActionsMenu({ label }: { label: string }): React.ReactElement {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        size="icon-xs"
                        aria-label={label}
                        // Dimmed until the row is hovered; stays full while focused or open.
                        className="opacity-30 transition-opacity group-hover/row:opacity-100 focus-visible:opacity-100 data-[popup-open]:opacity-100"
                    />
                }
            >
                <MoreHorizontal />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuItem>Edit</DropdownMenuItem>
                <DropdownMenuItem>Duplicate</DropdownMenuItem>
                <DropdownMenuItem>Copy link</DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem variant="destructive">Delete</DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

// Cell actions: an action button pushed to the end of a content cell with
// `ml-auto`, opening the dummy dropdown menu.
export const CellActions: Story = {
    render: () => (
        <Table className="max-w-2xl rounded-md border border-[var(--border)]">
            <TableHeader>
                <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Role</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {manyRows.slice(0, 6).map((row) => (
                    <TableRow key={row.id} className="group/row">
                        <TableCell className="font-medium">
                            <span className="flex items-center gap-2">
                                {row.name}
                                <span className="ml-auto">
                                    <ActionsMenu label={`Actions for ${row.name}`} />
                                </span>
                            </span>
                        </TableCell>
                        <TableCell>{row.role}</TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    ),
} satisfies Story

// Row actions: a trailing actions column with the same dummy menu at the end of
// each row.
export const RowActions: Story = {
    render: () => (
        <Table className="max-w-2xl rounded-md border border-[var(--border)]">
            <TableHeader>
                <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead className="w-0">
                        <span className="sr-only">Actions</span>
                    </TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {manyRows.slice(0, 6).map((row) => (
                    <TableRow key={row.id} className="group/row">
                        <TableCell className="font-medium">{row.name}</TableCell>
                        <TableCell>{row.email}</TableCell>
                        <TableCell>{row.role}</TableCell>
                        <TableCell className="w-0 text-right">
                            <ActionsMenu label={`Actions for ${row.name}`} />
                        </TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    ),
} satisfies Story
