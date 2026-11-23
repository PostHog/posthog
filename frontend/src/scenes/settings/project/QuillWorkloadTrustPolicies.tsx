import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconEllipsis, IconPlus } from '@posthog/icons'
import {
    Badge,
    Button,
    DataTable,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Skeleton,
    Switch,
    Text,
} from '@posthog/quill'

import { TimeSensitiveAuthenticationArea } from 'lib/components/TimeSensitiveAuthentication/TimeSensitiveAuthentication'
import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import type { WorkloadTrustPolicyApi } from '~/generated/core/api.schemas'

import { workloadTrustPoliciesLogic } from './workloadTrustPoliciesLogic'
import { WorkloadTrustPolicyModal } from './WorkloadTrustPolicyModal'

function RetryCallout({ message, onRetry }: { message: string; onRetry: () => void }): JSX.Element {
    return (
        <Item tone="destructive" size="sm">
            <ItemContent>
                <ItemDescription>{message}</ItemDescription>
            </ItemContent>
            <ItemActions>
                <Button variant="outline" onClick={onRetry}>
                    Retry
                </Button>
            </ItemActions>
        </Item>
    )
}

export function QuillWorkloadTrustPolicies({
    createDisabledReason,
}: {
    createDisabledReason: string | undefined
}): JSX.Element {
    const { policies, policiesLoading, policiesLoadFailed, providersLoadFailed, providerNames } =
        useValues(workloadTrustPoliciesLogic)
    const { setEditingPolicyId, deletePolicy, setPolicyEnabled, loadPolicies, loadProviders } =
        useActions(workloadTrustPoliciesLogic)

    const columns = useMemo<ColumnDef<WorkloadTrustPolicyApi>[]>(
        () => [
            {
                id: 'name',
                header: 'Name',
                enableSorting: false,
                cell: ({ row }) => (
                    <div className="flex flex-col">
                        <span className="font-semibold">{row.original.name}</span>
                        <Text size="xs" variant="muted" render={<span />}>
                            {providerNames[row.original.issuer] ?? row.original.issuer}
                        </Text>
                    </div>
                ),
            },
            {
                id: 'subject',
                header: 'Workload',
                enableSorting: false,
                cell: ({ row }) => (
                    <div className="flex flex-col">
                        <span className="font-mono">{row.original.subject_name}</span>
                        <Text size="xs" variant="muted" render={<span />}>
                            {row.original.claim_labels.subject} {row.original.subject}
                        </Text>
                    </div>
                ),
            },
            {
                id: 'conditions',
                header: 'Conditions',
                enableSorting: false,
                cell: ({ row }) => (
                    <span className="flex flex-wrap gap-1">
                        {Object.entries(row.original.conditions ?? {}).map(([claim, value]) => (
                            <Badge key={claim}>
                                {row.original.claim_labels.conditions[claim] ?? claim}: {value}
                            </Badge>
                        ))}
                    </span>
                ),
            },
            {
                id: 'scopes',
                header: 'Scopes',
                enableSorting: false,
                cell: ({ row }) => (
                    <span className="flex flex-wrap gap-1">
                        {row.original.scopes.map((scope) => (
                            <Badge key={scope}>{scope}</Badge>
                        ))}
                    </span>
                ),
            },
            {
                id: 'enabled',
                header: 'Enabled',
                enableSorting: false,
                cell: ({ row }) => (
                    <Switch
                        checked={!!row.original.enabled}
                        onCheckedChange={(enabled: boolean) => setPolicyEnabled({ policy: row.original, enabled })}
                        disabledReason={policiesLoading ? 'Saving' : undefined}
                        aria-label={`Enable ${row.original.name}`}
                        data-attr="workload-trust-policy-enabled"
                    />
                ),
            },
            {
                id: 'created',
                header: 'Created',
                enableSorting: false,
                cell: ({ row }) => (
                    <div className="flex flex-col gap-1">
                        {row.original.created_by ? (
                            <ProfilePicture
                                user={{
                                    first_name: row.original.created_by.first_name,
                                    last_name: row.original.created_by.last_name,
                                    email: row.original.created_by.email,
                                }}
                                size="sm"
                                showName
                            />
                        ) : null}
                        <TZLabel time={row.original.created_at} className="text-muted-foreground text-xs" />
                    </div>
                ),
            },
            {
                id: 'actions',
                header: '',
                enableSorting: false,
                cell: ({ row }) => (
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={<Button size="icon" aria-label="Policy actions" tooltip="Policy actions" />}
                        >
                            <IconEllipsis />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => setEditingPolicyId(row.original.id)}>
                                Edit
                            </DropdownMenuItem>
                            <DropdownMenuItem
                                variant="destructive"
                                onClick={() => deletePolicy(row.original)}
                                data-attr="workload-trust-policy-delete"
                            >
                                Delete
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                ),
            },
        ],
        [providerNames, policiesLoading, setPolicyEnabled, setEditingPolicyId, deletePolicy]
    )

    return (
        <TimeSensitiveAuthenticationArea>
            <div className="flex flex-col items-start gap-2">
                <Text size="xs" render={<p className="m-0" />}>
                    A trusted workload, such as a CI job, gets short-lived tokens for this project, so you don't have to
                    store an API key with it. Tokens act as the organization owner and carry only the scopes the policy
                    lists.
                </Text>
                <Button
                    variant="primary"
                    onClick={() => setEditingPolicyId('new')}
                    disabledReason={createDisabledReason}
                    data-attr="workload-trust-policy-create"
                >
                    <IconPlus />
                    Add trusted workload
                </Button>
                {providersLoadFailed ? (
                    <RetryCallout message="Couldn't load the supported providers." onRetry={() => loadProviders()} />
                ) : null}
                {policiesLoadFailed ? (
                    <RetryCallout message="Couldn't load trusted workloads." onRetry={() => loadPolicies()} />
                ) : policiesLoading && policies === null ? (
                    <Skeleton className="h-24 w-full" />
                ) : (
                    <DataTable
                        columns={columns}
                        data={policies ?? []}
                        fullWidth
                        getRowId={(policy) => policy.id}
                        empty={
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                No trusted workloads yet. No workload can get tokens for this project.
                            </Text>
                        }
                    />
                )}
                <WorkloadTrustPolicyModal />
            </div>
        </TimeSensitiveAuthenticationArea>
    )
}
