import type { Meta, StoryObj } from '@storybook/react'
import {
    type ColumnDef,
    type ColumnSizingState,
    type RowSelectionState,
    type SortingState,
} from '@tanstack/react-table'
import * as React from 'react'

import { Badge, Checkbox, Field, Label } from '@posthog/quill-primitives'

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

const clickableColumns: ColumnDef<Person>[] = [
    ...fullWidthColumns,
    {
        id: 'selection',
        header: 'Select',
        enableSorting: false,
        cell: ({ row }) => {
            const id = `select-${row.original.id}`

            return (
                <Field orientation="horizontal">
                    <Checkbox id={id} />
                    <Label htmlFor={id}>Select</Label>
                </Field>
            )
        },
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

export const ClickableRows: Story = {
    render: () => (
        <DataTable
            columns={clickableColumns}
            data={people}
            fullWidth
            onRowClick={() => undefined}
            className="rounded-md border border-[var(--border)]"
        />
    ),
}

// Client-side pagination — pass `pageSize` to page the data and render a pager
// below the table. `pageSizeOptions` adds a rows-per-page selector.
// The caller owns the sort, as a paged list sorted on the server must. The table only reports the clicks.
export const ControlledSorting: Story = {
    render: function Render() {
        const [sorting, setSorting] = React.useState<SortingState>([{ id: 'name', desc: true }])
        const [sort] = sorting
        const sorted = [...people].sort((a, b) => (sort ? a.name.localeCompare(b.name) * (sort.desc ? -1 : 1) : 0))
        return (
            <DataTable
                columns={[
                    { accessorKey: 'name', header: 'Name', sortDescFirst: true },
                    { accessorKey: 'email', header: 'Email', enableSorting: false },
                ]}
                data={sorted}
                sorting={sorting}
                onSortingChange={setSorting}
            />
        )
    },
} satisfies Story

// Hover the header to see the column edges, and a header cell to see its handle. The columns fit their content until
// the first drag, and a drag only ever changes the dragged column. A double click on an edge resets the column.
export const ResizableColumns: Story = {
    render: () => (
        <DataTable
            columns={[
                { accessorKey: 'name', header: 'Name', minSize: 120, meta: { expand: true } },
                { accessorKey: 'email', header: 'Email', maxSize: 400 },
                { accessorKey: 'role', header: 'Role' },
                { accessorKey: 'status', header: 'Status', enableResizing: false },
            ]}
            data={people}
            fullWidth
            resizableColumns
            className="max-w-3xl rounded-md border border-[var(--border)]"
        />
    ),
} satisfies Story

// `columnSizing` restores saved widths from the first paint, and `onColumnSizingChange` is where to save them.
export const SavedColumnWidths: Story = {
    render: function Render() {
        const [columnSizing, setColumnSizing] = React.useState<ColumnSizingState>({ email: 320 })
        return (
            <DataTable
                columns={columns}
                data={people}
                resizableColumns
                columnSizing={columnSizing}
                onColumnSizingChange={setColumnSizing}
                className="rounded-md border border-[var(--border)]"
            />
        )
    },
} satisfies Story

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

// Invited users can't be selected: `rowSelectionDisabledReason` disables their checkboxes and says why in a tooltip,
// and a shift-click range skips them.
export const SelectableRows: Story = {
    render: function Render() {
        const [rowSelection, setRowSelection] = React.useState<RowSelectionState>({ 'USR-2': true, 'USR-3': true })
        const selected = Object.keys(rowSelection).length
        return (
            <div className="flex max-w-3xl flex-col gap-2">
                <p className="text-sm text-muted-foreground">{`${selected} selected`}</p>
                <DataTable
                    columns={columns}
                    data={people}
                    selectable
                    getRowId={(person) => person.id}
                    rowSelectionLabel={(person) => `Select ${person.name}`}
                    rowSelectionDisabledReason={(person) =>
                        person.status === 'Active' ? null : "Invited users can't be selected until they accept."
                    }
                    rowSelection={rowSelection}
                    onRowSelectionChange={setRowSelection}
                    className="rounded-md border border-[var(--border)]"
                />
            </div>
        )
    },
} satisfies Story

interface Track {
    id: string
    name: string
    owner: string
    lanes: { name: string; from: number; to: number }[]
}

const tracks: Track[] = [
    {
        id: 'quiet-theme',
        name: 'Quiet theme',
        owner: 'Ava',
        lanes: [
            { name: 'quiet-theme flag', from: 2, to: 18 },
            { name: 'Launch email', from: 12, to: 13 },
        ],
    },
    {
        id: 'faster-search',
        name: 'Faster search',
        owner: 'Ben',
        lanes: [
            { name: 'search-v2 flag', from: 0, to: 22 },
            { name: 'Ranking test', from: 6, to: 20 },
            { name: 'Beta opt-in', from: 4, to: 10 },
        ],
    },
    { id: 'csv-export', name: 'CSV export', owner: 'Cara', lanes: [{ name: 'csv-export flag', from: 9, to: 26 }] },
]

const DAYS = 30
const DAY_WIDTH = 28
const LANE_HEIGHT = 28

function TrackBar({ from, to }: { from: number; to: number }): React.ReactElement {
    return (
        <div className="relative" style={{ height: LANE_HEIGHT, width: DAYS * DAY_WIDTH }}>
            <div
                className="absolute top-1.5 h-4 rounded-full bg-[var(--info)]"
                style={{ left: from * DAY_WIDTH, width: (to - from) * DAY_WIDTH }}
            />
        </div>
    )
}

export const StickyColumnAndGrowingRows: Story = {
    render: function StickyColumnAndGrowingRowsStory() {
        const [open, setOpen] = React.useState<Record<string, boolean>>({ 'faster-search': true })
        const trackColumns = React.useMemo<ColumnDef<Track>[]>(
            () => [
                {
                    id: 'name',
                    header: 'Release',
                    size: 200,
                    enableSorting: false,
                    meta: { sticky: 'left' },
                    cell: ({ row }) => (
                        <div className="flex flex-col">
                            <div className="flex items-center gap-2" style={{ height: LANE_HEIGHT }}>
                                <span className="font-medium">{row.original.name}</span>
                                <span className="text-muted-foreground">{row.original.owner}</span>
                            </div>
                            {open[row.original.id] &&
                                row.original.lanes.map((lane) => (
                                    <div
                                        key={lane.name}
                                        className="flex items-center pl-4 text-muted-foreground"
                                        style={{ height: LANE_HEIGHT }}
                                    >
                                        {lane.name}
                                    </div>
                                ))}
                        </div>
                    ),
                },
                {
                    id: 'timeline',
                    header: 'Next 30 days',
                    enableSorting: false,
                    cell: ({ row }) => {
                        const { lanes } = row.original
                        const from = Math.min(...lanes.map((lane) => lane.from))
                        const to = Math.max(...lanes.map((lane) => lane.to))
                        return (
                            <div className="flex flex-col">
                                <TrackBar from={from} to={to} />
                                {open[row.original.id] &&
                                    lanes.map((lane) => <TrackBar key={lane.name} from={lane.from} to={lane.to} />)}
                            </div>
                        )
                    },
                },
            ],
            [open]
        )
        return (
            <DataTable
                columns={trackColumns}
                data={tracks}
                getRowId={(track) => track.id}
                onRowClick={(track) => setOpen((state) => ({ ...state, [track.id]: !state[track.id] }))}
                className="max-w-xl rounded-md border border-[var(--border)]"
            />
        )
    },
}
