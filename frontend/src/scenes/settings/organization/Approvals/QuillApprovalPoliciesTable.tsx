import type { ColumnDef } from '@tanstack/react-table'

import { IconEllipsis } from '@posthog/icons'
import {
    Button,
    Card,
    DataTable,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Skeleton,
} from '@posthog/quill'

import { getApprovalActionLabel } from 'scenes/approvals/utils'

import { ApprovalPolicy } from '~/types'

import { describeApprovers } from './describeApprovers'
import { QuillExperimentPoliciesNotice } from './QuillExperimentPoliciesNotice'

export function QuillApprovalPoliciesTable({
    policies,
    loading,
    restrictionReason,
    showExperimentPoliciesNotice,
    onAdd,
    onEdit,
    onDelete,
}: {
    policies: ApprovalPolicy[]
    loading: boolean
    restrictionReason: string | null
    showExperimentPoliciesNotice: boolean
    onAdd: () => void
    onEdit: (policy: ApprovalPolicy) => void
    onDelete: (policy: ApprovalPolicy) => void
}): JSX.Element {
    const columns: ColumnDef<ApprovalPolicy>[] = [
        {
            id: 'action_key',
            header: 'Action',
            meta: { expand: true },
            cell: ({ row }) => getApprovalActionLabel(row.original.action_key),
        },
        {
            id: 'approvers',
            header: 'Approvers',
            cell: ({ row }) => describeApprovers(row.original),
        },
        {
            id: 'quorum',
            header: 'Approvals required',
            cell: ({ row }) => row.original.approver_config?.quorum || 1,
        },
        {
            id: 'allow_self_approve',
            header: 'Self-approve',
            cell: ({ row }) => (row.original.allow_self_approve ? 'Yes' : 'No'),
        },
        {
            id: 'enabled',
            header: 'Status',
            cell: ({ row }) => (row.original.enabled ? 'Enabled' : 'Disabled'),
        },
        {
            id: 'actions',
            header: '',
            enableSorting: false,
            meta: { align: 'right' },
            cell: ({ row }) => (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={<Button size="icon" aria-label="More actions" tooltip="More actions" />}
                    >
                        <IconEllipsis />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => onEdit(row.original)} disabledReason={restrictionReason}>
                            Edit
                        </DropdownMenuItem>
                        <DropdownMenuItem
                            variant="destructive"
                            onClick={() => onDelete(row.original)}
                            disabledReason={restrictionReason}
                        >
                            Delete
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            {showExperimentPoliciesNotice && <QuillExperimentPoliciesNotice />}
            <div className="flex justify-end">
                <Button variant="primary" onClick={onAdd} disabledReason={restrictionReason}>
                    Add policy
                </Button>
            </div>
            {loading && policies.length === 0 ? (
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-8 w-full" />
                    <Skeleton className="h-8 w-full" />
                    <Skeleton className="h-8 w-full" />
                </div>
            ) : (
                <Card size="sm" flush className="pt-0">
                    <DataTable
                        columns={columns}
                        data={policies}
                        fullWidth
                        size="sm"
                        empty="No approval policies configured"
                    />
                </Card>
            )}
        </div>
    )
}
