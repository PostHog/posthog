import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconPlus } from '@posthog/icons'
import { Badge, Button, DataTable, Input, Skeleton, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import type { ServiceAccountApi } from '~/generated/core/api.schemas'

import { QuillCreateServiceAccountModal } from './QuillCreateServiceAccountModal'
import { ServiceAccountsLogicProps, serviceAccountsLogic } from './serviceAccountsLogic'

export function QuillServiceAccountsTable(props: ServiceAccountsLogicProps): JSX.Element {
    const logic = serviceAccountsLogic(props)
    const { accounts, filteredAccounts, accountsLoading, loadFailed, search } = useValues(logic)
    const { loadAccounts, setSearch, setCreating, selectAccount } = useActions(logic)
    const columns = useMemo<ColumnDef<ServiceAccountApi>[]>(
        () => [
            {
                accessorKey: 'name',
                header: 'Name',
                cell: ({ row }) => (
                    <Button
                        variant="link-foreground"
                        onClick={() => selectAccount(row.original.id)}
                        data-attr="service-account-open"
                    >
                        <span className="truncate max-w-60">{row.original.name}</span>
                    </Button>
                ),
            },
            {
                accessorKey: 'is_active',
                header: 'Status',
                cell: ({ row }) => (
                    <Badge variant={row.original.is_active ? 'success' : 'default'}>
                        {row.original.is_active ? 'Active' : 'Disabled'}
                    </Badge>
                ),
            },
            {
                accessorKey: 'created_at',
                header: 'Created',
                cell: ({ row }) => <TZLabel time={row.original.created_at} />,
            },
        ],
        [selectAccount]
    )

    return (
        <div data-quill className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-2">
                <Input
                    type="search"
                    placeholder="Search service accounts"
                    aria-label="Search service accounts"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    className="max-w-80"
                />
                <Button
                    variant="primary"
                    onClick={() => setCreating(true)}
                    data-attr="service-account-create"
                    className="ml-auto"
                >
                    <IconPlus />
                    Create service account
                </Button>
            </div>
            {loadFailed && !accountsLoading ? (
                <div role="alert">
                    <Text size="xs">Couldn't load service accounts. Try again.</Text>
                    <Button onClick={() => loadAccounts()}>Retry</Button>
                </div>
            ) : accounts === null ? (
                <Skeleton className="h-32" />
            ) : (
                <DataTable
                    data={filteredAccounts}
                    columns={columns}
                    fullWidth
                    getRowId={(account) => account.id}
                    pageSize={20}
                    empty={
                        <Text size="xs">
                            {search.trim()
                                ? 'No service accounts match your search.'
                                : 'No service accounts yet. Create one for an integration or automation.'}
                        </Text>
                    }
                />
            )}
            <QuillCreateServiceAccountModal {...props} />
        </div>
    )
}
