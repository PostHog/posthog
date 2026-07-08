import type { Meta, StoryObj } from '@storybook/react'
import { type ColumnDef } from '@tanstack/react-table'
import * as React from 'react'

import { Badge } from '@posthog/quill-primitives'

import { DataTable } from './data-table'

interface Person {
    id: string
    name: string
    email: string
    role: string
    signups: number
    status: 'Active' | 'Invited'
}

const people: Person[] = Array.from({ length: 8 }, (_, i) => ({
    id: `USR-${i + 1}`,
    name: ['Ava', 'Ben', 'Cara', 'Dan', 'Eve', 'Finn', 'Gia', 'Hugo'][i],
    email: `${['ava', 'ben', 'cara', 'dan', 'eve', 'finn', 'gia', 'hugo'][i]}@example.com`,
    role: i % 3 === 0 ? 'Admin' : 'Member',
    signups: [42, 17, 88, 5, 63, 29, 71, 13][i],
    status: i % 4 === 0 ? 'Invited' : 'Active',
}))

// Active users read as success, pending invites as warning — same semantic
// mapping the Table primitive's Status column uses.
function StatusBadge({ status }: { status: string }): React.ReactElement {
    const variant = status === 'Active' ? 'success' : status === 'Invited' ? 'warning' : 'destructive'
    return <Badge variant={variant}>{status}</Badge>
}

const columns: ColumnDef<Person>[] = [
    {
        accessorKey: 'name',
        header: 'Name',
        cell: (info) => <span className="font-medium">{info.getValue<string>()}</span>,
    },
    { accessorKey: 'email', header: 'Email' },
    { accessorKey: 'role', header: 'Role' },
    {
        accessorKey: 'signups',
        header: 'Signups',
        // `meta.align` aligns the header and every body cell on the same axis.
        meta: { align: 'right' },
        cell: (info) => <span className="tabular-nums">{info.getValue<number>()}</span>,
    },
    {
        accessorKey: 'status',
        header: 'Status',
        enableSorting: false,
        cell: (info) => <StatusBadge status={info.getValue<string>()} />,
    },
]

const meta = {
    title: 'Components/DataTable',
    tags: ['autodocs'],
} satisfies Meta

export default meta
type Story = StoryObj<typeof meta>

// Click a sortable header (Name, Email, Role, Signups) to toggle asc → desc → off.
export const Default: Story = {
    render: () => (
        <>
            <p className="mb-4 text-sm text-muted-foreground">
                Built with {/* eslint-disable-next-line react/forbid-elements -- plain link in a storybook demo */}
                <a
                    className="text-primary underline"
                    href="https://tanstack.com/table/latest/docs/framework/react/guides/getting-started"
                    target="_blank"
                    rel="noreferrer"
                >
                    TanStack Table
                </a>{' '}
                and quill primitives.
            </p>
            <DataTable columns={columns} data={people} className="max-w-2xl rounded-md border border-[var(--border)]" />
        </>
    ),
}

const manyPeople: Person[] = Array.from({ length: 50 }, (_, i) => ({
    id: `USR-${i + 1}`,
    name: `Person ${i + 1}`,
    email: `person${i + 1}@example.com`,
    role: i % 3 === 0 ? 'Admin' : 'Member',
    signups: (i * 37) % 100,
    status: i % 4 === 0 ? 'Invited' : 'Active',
}))

export const StickyHeader: Story = {
    render: () => (
        <DataTable
            columns={columns}
            data={manyPeople}
            stickyHeader
            className="h-72 max-w-2xl rounded-md border border-[var(--border)]"
        />
    ),
}

// Full-width table: `fullWidth` stretches it to the container and the Name
// column (marked `meta: { expand: true }`) absorbs the slack while the rest stay
// content-sized.
const fullWidthColumns: ColumnDef<Person>[] = [
    {
        accessorKey: 'name',
        header: 'Name',
        meta: { expand: true },
        cell: (info) => (
            <div className="flex min-w-0 flex-col">
                <span className="truncate font-medium">{info.getValue<string>()}</span>
                <span className="truncate text-muted-foreground">{info.row.original.email}</span>
            </div>
        ),
    },
    { accessorKey: 'role', header: 'Role' },
    {
        accessorKey: 'signups',
        header: 'Signups',
        meta: { align: 'right' },
        cell: (info) => <span className="tabular-nums">{info.getValue<number>()}</span>,
    },
    {
        accessorKey: 'status',
        header: 'Status',
        enableSorting: false,
        meta: { align: 'center' },
        cell: (info) => <StatusBadge status={info.getValue<string>()} />,
    },
]

export const FullWidth: Story = {
    render: () => (
        <DataTable
            columns={fullWidthColumns}
            data={people}
            fullWidth
            className="rounded-md border border-[var(--border)]"
        />
    ),
}

// Client-side pagination — pass `pageSize` to page the data and render a pager
// below the table. `pageSizeOptions` adds a rows-per-page selector.
export const Paginated: Story = {
    render: () => (
        <DataTable
            columns={columns}
            data={manyPeople}
            pageSize={10}
            pageSizeOptions={[10, 25, 50]}
            className="max-w-2xl rounded-md border border-[var(--border)]"
        />
    ),
}

// Full width + pagination together — the table fills the container and the pager
// spans the same width below it (row range and page-size selector on the left,
// page controls on the right).
export const FullWidthPaginated: Story = {
    render: () => (
        <DataTable
            columns={fullWidthColumns}
            data={manyPeople}
            fullWidth
            pageSize={10}
            pageSizeOptions={[10, 25, 50]}
            className="rounded-md border border-[var(--border)]"
        />
    ),
}

