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
        cell: (info) => <span className="tabular-nums">{info.getValue<number>()}</span>,
    },
    {
        accessorKey: 'status',
        header: 'Status',
        enableSorting: false,
        cell: (info) => <Badge>{info.getValue<string>()}</Badge>,
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
                Built with <a className="text-primary underline" href="https://tanstack.com/table/latest/docs/framework/react/guides/getting-started" target="_blank">TanStack Table</a> and quill primitives.
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

export const Empty: Story = {
    render: () => (
        <DataTable columns={columns} data={[]} className="max-w-2xl rounded-md border border-[var(--border)]" />
    ),
}
