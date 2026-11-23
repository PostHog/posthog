import type { ColumnDef } from '@tanstack/react-table'

import {
    Badge,
    Button,
    Card,
    DataTable,
    Field,
    FieldLabel,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { getApprovalActionLabel, getApprovalResourceName, getApprovalResourceUrl } from 'scenes/approvals/utils'
import { urls } from 'scenes/urls'

import { ChangeRequest, ChangeRequestState } from '~/types'

import { QuillChangeRequestTableActions } from './QuillChangeRequestTableActions'

const STATUS_FILTER_OPTIONS: { label: string; value: ChangeRequestState | null }[] = [
    { label: 'All', value: null },
    { label: 'Pending', value: ChangeRequestState.Pending },
    { label: 'Approved', value: ChangeRequestState.Approved },
    { label: 'Applied', value: ChangeRequestState.Applied },
    { label: 'Rejected', value: ChangeRequestState.Rejected },
    { label: 'Expired', value: ChangeRequestState.Expired },
    { label: 'Failed', value: ChangeRequestState.Failed },
]

const STATUS_BADGE_VARIANTS = {
    [ChangeRequestState.Pending]: 'default',
    [ChangeRequestState.Approved]: 'info',
    [ChangeRequestState.Applied]: 'success',
    [ChangeRequestState.Rejected]: 'destructive',
    [ChangeRequestState.Expired]: 'warning',
    [ChangeRequestState.Failed]: 'destructive',
} as const

function TableLink({ to, children }: { to: string; children: React.ReactNode }): JSX.Element {
    return (
        <Button variant="link-foreground" size="sm" nativeButton={false} render={<LinkPrimitive to={to} />}>
            {children}
        </Button>
    )
}

export function QuillChangeRequestsTable({
    changeRequests,
    loading,
    stateFilter,
    hasMore,
    onStateFilterChange,
    onLoadMore,
    onApprove,
    onReject,
}: {
    changeRequests: ChangeRequest[]
    loading: boolean
    stateFilter: ChangeRequestState | null
    hasMore: boolean
    onStateFilterChange: (state: ChangeRequestState | null) => void
    onLoadMore: () => void
    onApprove: (id: string) => void
    onReject: (id: string, reason: string) => void
}): JSX.Element {
    const columns: ColumnDef<ChangeRequest>[] = [
        {
            id: 'action_key',
            header: 'Action',
            cell: ({ row }) => (
                <TableLink to={urls.approval(row.original.id)}>
                    {getApprovalActionLabel(row.original.action_key)}
                </TableLink>
            ),
        },
        {
            id: 'resource',
            header: 'Resource',
            meta: { expand: true },
            cell: ({ row }) => {
                const resourceUrl = getApprovalResourceUrl(row.original.resource_type, row.original.resource_id)
                const name = getApprovalResourceName(row.original.resource_type, row.original.intent)
                return resourceUrl && name ? <TableLink to={resourceUrl}>{name}</TableLink> : name
            },
        },
        {
            id: 'created_by',
            header: 'Requested by',
            cell: ({ row }) => <ProfilePicture user={row.original.created_by} size="md" showName />,
        },
        {
            id: 'state',
            header: 'Status',
            cell: ({ row }) => (
                <Badge variant={STATUS_BADGE_VARIANTS[row.original.state]} className="uppercase">
                    {row.original.state}
                </Badge>
            ),
        },
        {
            id: 'approvals',
            header: 'Approvals',
            cell: ({ row }) => {
                const required = row.original.policy_snapshot?.quorum || 1
                const current = row.original.approvals?.length || 0
                return <span translate="no">{`${current} / ${required}`}</span>
            },
        },
        {
            id: 'created_at',
            header: 'Created',
            cell: ({ row }) => <TZLabel time={row.original.created_at} />,
        },
        {
            id: 'expires_at',
            header: 'Expires',
            cell: ({ row }) => {
                if (row.original.state !== ChangeRequestState.Pending || !row.original.expires_at) {
                    return null
                }

                const hoursLeft = dayjs(row.original.expires_at).diff(dayjs(), 'hours')
                const toneClass =
                    hoursLeft < 0 ? 'text-destructive-foreground' : hoursLeft < 24 ? 'text-warning-foreground' : ''

                return (
                    <span className={toneClass}>
                        <TZLabel time={row.original.expires_at} />
                    </span>
                )
            },
        },
        {
            id: 'actions',
            header: '',
            enableSorting: false,
            meta: { align: 'right' },
            cell: ({ row }) => (
                <QuillChangeRequestTableActions
                    changeRequest={row.original}
                    onApprove={onApprove}
                    onReject={onReject}
                />
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <Field orientation="horizontal" className="w-fit">
                <FieldLabel htmlFor="change-requests-status-filter">Status</FieldLabel>
                <Select<ChangeRequestState | null>
                    items={STATUS_FILTER_OPTIONS}
                    value={stateFilter}
                    onValueChange={(value) => onStateFilterChange(value ?? null)}
                >
                    <SelectTrigger id="change-requests-status-filter">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        {STATUS_FILTER_OPTIONS.map((option) => (
                            <SelectItem key={option.label} value={option.value}>
                                {option.label}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            </Field>

            {loading && changeRequests.length === 0 ? (
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-8 w-full" />
                    <Skeleton className="h-8 w-full" />
                    <Skeleton className="h-8 w-full" />
                </div>
            ) : (
                <Card size="sm" flush className="pt-0" data-attr="approvals-table">
                    <DataTable
                        columns={columns}
                        data={changeRequests}
                        fullWidth
                        size="sm"
                        empty="No change requests found"
                    />
                </Card>
            )}

            {hasMore && (
                <div className="flex justify-center">
                    <Button
                        variant="outline"
                        onClick={onLoadMore}
                        loading={loading}
                        disabledReason={loading ? 'Loading change requests' : undefined}
                    >
                        Load more
                    </Button>
                </div>
            )}
        </div>
    )
}
