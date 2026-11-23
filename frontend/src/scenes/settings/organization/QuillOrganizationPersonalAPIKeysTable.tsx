import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconEllipsis, IconSearch } from '@posthog/icons'
import {
    Button,
    DataTable,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Empty,
    EmptyHeader,
    EmptyTitle,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Skeleton,
    Text,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { QuillTagList } from 'scenes/settings/user/QuillTagList'
import { ScopeGroupSummary } from 'scenes/settings/user/scopes/ScopeGroupSummary'

import type { OrganizationPersonalAPIKeyApi } from 'products/platform_features/frontend/generated/api.schemas'

import { KeyAction, organizationPersonalAPIKeysLogic } from './organizationPersonalAPIKeysLogic'

function QuillAccessScope({
    accessScope,
}: {
    accessScope: OrganizationPersonalAPIKeyApi['access_scope']
}): JSX.Element {
    if (accessScope.type === 'all') {
        return (
            <Text size="xs" variant="muted" render={<span />}>
                All projects (unscoped)
            </Text>
        )
    }

    if (accessScope.type === 'organization') {
        return (
            <Text size="xs" render={<span />}>
                Organization-wide
            </Text>
        )
    }

    return <QuillTagList tags={(accessScope.projects ?? []).map((project) => project.name)} />
}

function EmptyMessage({ children }: { children: string }): JSX.Element {
    return (
        <Empty>
            <EmptyHeader>
                <EmptyTitle>{children}</EmptyTitle>
            </EmptyHeader>
        </Empty>
    )
}

export interface QuillOrganizationPersonalAPIKeysTableProps {
    ownerLabel: (owner: OrganizationPersonalAPIKeyApi['owner']) => string
    isBulkRunning: (action: KeyAction) => boolean
    actionDisabledReason: string | null
    bulkDisabledReason: string | null
    onRollKey: (key: OrganizationPersonalAPIKeyApi) => void
    onRevokeKey: (key: OrganizationPersonalAPIKeyApi) => void
    onRollAll: () => void
    onRevokeAll: () => void
}

export function QuillOrganizationPersonalAPIKeysTable({
    ownerLabel,
    isBulkRunning,
    actionDisabledReason,
    bulkDisabledReason,
    onRollKey,
    onRevokeKey,
    onRollAll,
    onRevokeAll,
}: QuillOrganizationPersonalAPIKeysTableProps): JSX.Element {
    const { filteredKeys, keysLoading, search, keyActionInFlight } = useValues(organizationPersonalAPIKeysLogic)
    const { setSearch } = useActions(organizationPersonalAPIKeysLogic)

    const columns = useMemo<ColumnDef<OrganizationPersonalAPIKeyApi>[]>(
        () => [
            {
                id: 'owner',
                header: 'Owner',
                accessorFn: (key) => ownerLabel(key.owner),
                cell: ({ row }) => (
                    <div className="flex flex-col">
                        <Text size="xs" render={<span />}>
                            {ownerLabel(row.original.owner)}
                        </Text>
                        <Text size="xs" variant="muted" render={<span />}>
                            {row.original.owner.email}
                        </Text>
                    </div>
                ),
            },
            {
                id: 'mask_value',
                header: 'Masked value',
                accessorKey: 'mask_value',
                cell: ({ row }) => <span className="font-mono">{row.original.mask_value}</span>,
            },
            {
                id: 'scopes',
                header: 'Scopes',
                enableSorting: false,
                cell: ({ row }) => (
                    <QuillTagList
                        tags={[...row.original.scopes]}
                        tooltip={<ScopeGroupSummary scopes={row.original.scopes} />}
                    />
                ),
            },
            {
                id: 'access_scope',
                header: 'Access scope',
                enableSorting: false,
                cell: ({ row }) => <QuillAccessScope accessScope={row.original.access_scope} />,
            },
            {
                id: 'last_used_at',
                header: 'Last used',
                accessorFn: (key) => new Date(key.last_used_at ?? 0).getTime(),
                cell: ({ row }) =>
                    row.original.last_used_at ? (
                        <TZLabel time={row.original.last_used_at} />
                    ) : (
                        <Text size="xs" variant="muted" render={<span />}>
                            Never
                        </Text>
                    ),
            },
            {
                id: 'created_at',
                header: 'Created',
                accessorFn: (key) => new Date(key.created_at).getTime(),
                cell: ({ row }) => <TZLabel time={row.original.created_at} />,
            },
            {
                id: 'actions',
                header: '',
                enableSorting: false,
                meta: { align: 'right' },
                cell: ({ row }) => {
                    const key = row.original
                    const running = keyActionInFlight === key.id
                    const label = `Actions for key ${key.mask_value}`

                    return (
                        <DropdownMenu>
                            <DropdownMenuTrigger
                                render={
                                    <Button
                                        size="icon"
                                        aria-label={label}
                                        tooltip={label}
                                        loading={running}
                                        disabledReason={running ? null : actionDisabledReason}
                                        data-attr="organization-personal-api-key-actions"
                                    />
                                }
                            >
                                <IconEllipsis />
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                                <DropdownMenuItem
                                    onClick={() => onRollKey(key)}
                                    data-attr="organization-personal-api-key-roll"
                                >
                                    Roll key
                                </DropdownMenuItem>
                                <DropdownMenuItem
                                    variant="destructive"
                                    onClick={() => onRevokeKey(key)}
                                    data-attr="organization-personal-api-key-revoke"
                                >
                                    Revoke key
                                </DropdownMenuItem>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    )
                },
            },
        ],
        [ownerLabel, keyActionInFlight, actionDisabledReason, onRollKey, onRevokeKey]
    )

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
                <InputGroup size="sm" className="grow min-w-60 max-w-80">
                    <InputGroupAddon align="inline-start">
                        <IconSearch />
                    </InputGroupAddon>
                    <InputGroupInput
                        type="search"
                        placeholder="Search by name, email, or scope"
                        aria-label="Search by name, email, or scope"
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                    />
                </InputGroup>
                <div className="flex flex-wrap gap-2 ml-auto">
                    <Button
                        variant="outline"
                        loading={isBulkRunning('roll')}
                        disabledReason={isBulkRunning('roll') ? null : bulkDisabledReason}
                        onClick={onRollAll}
                        data-attr="organization-personal-api-keys-roll-all"
                    >
                        Roll all keys
                    </Button>
                    <Button
                        variant="outline"
                        loading={isBulkRunning('revoke')}
                        disabledReason={isBulkRunning('revoke') ? null : bulkDisabledReason}
                        onClick={onRevokeAll}
                        data-attr="organization-personal-api-keys-revoke-all"
                    >
                        Revoke all keys
                    </Button>
                </div>
            </div>
            {keysLoading && filteredKeys.length === 0 ? (
                <Skeleton className="h-40" />
            ) : (
                <div aria-busy={keysLoading}>
                    <DataTable
                        columns={columns}
                        data={filteredKeys}
                        fullWidth
                        getRowId={(key) => key.id}
                        pageSize={25}
                        empty={
                            <EmptyMessage>
                                {search.trim()
                                    ? 'No personal API keys match your search.'
                                    : 'No personal API keys have access to this organization.'}
                            </EmptyMessage>
                        }
                    />
                </div>
            )}
        </div>
    )
}
