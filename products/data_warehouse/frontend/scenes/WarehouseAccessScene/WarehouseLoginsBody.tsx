import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import {
    Button,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Skeleton,
    Table,
    TableBody,
    TableHead,
    TableHeader,
    TableRow,
} from '@posthog/quill'

import { WarehouseLoginRow } from './WarehouseLoginRow'
import { warehouseLoginsLogic } from './warehouseLoginsLogic'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

export function WarehouseLoginsBody(): JSX.Element {
    const { logins, loginsFailed } = useValues(warehouseLoginsLogic)
    const { loadLogins } = useActions(warehouseLoginsLogic)

    if (logins === null && !loginsFailed) {
        return <Skeleton className="h-24 w-full" />
    }
    if (logins === null) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyTitle>Couldn't load logins</EmptyTitle>
                    <EmptyDescription>Check your connection and try again.</EmptyDescription>
                </EmptyHeader>
                <Button
                    onClick={() => {
                        posthog.capture('warehouse access logins retry clicked')
                        loadLogins()
                    }}
                    data-attr="warehouse-access-logins-retry"
                >
                    Try again
                </Button>
            </Empty>
        )
    }
    if (logins.length === 0) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyTitle>No logins yet</EmptyTitle>
                    <EmptyDescription>Create a login for a project to connect a tool to it.</EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }
    return (
        <div className="max-w-full overflow-x-auto">
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead>Username</TableHead>
                        <TableHead>Access</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Queries, 30 days</TableHead>
                        <TableHead>Scanned, 30 days</TableHead>
                        <TableHead>Created</TableHead>
                        <TableHead>
                            <span className="sr-only">Actions</span>
                        </TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {logins.map((login) => (
                        <WarehouseLoginRow key={login.username} login={login} />
                    ))}
                </TableBody>
            </Table>
        </div>
    )
}
