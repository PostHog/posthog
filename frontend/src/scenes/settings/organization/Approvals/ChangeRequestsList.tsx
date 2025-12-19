import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonDialog, LemonInput, LemonSelect, LemonTable, LemonTag, lemonToast } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { cn } from 'lib/utils/css-classes'
import { approvalsLogic } from 'scenes/approvals/approvalsLogic'
import { getChangeRequestButtonVisibility } from 'scenes/approvals/changeRequestsLogic'
import { getApprovalActionLabel, getApprovalResourceName, getApprovalResourceUrl } from 'scenes/approvals/utils'
import { urls } from 'scenes/urls'

import { ChangeRequest, ChangeRequestState } from '~/types'

export function ChangeRequestsList(): JSX.Element {
    const { changeRequests, changeRequestsDataLoading, filters, hasMore } = useValues(approvalsLogic)
    const { setFilters, loadMore, approveChangeRequest, rejectChangeRequest } = useActions(approvalsLogic)

    const columns: LemonTableColumn<ChangeRequest, keyof ChangeRequest | undefined>[] = [
        {
            title: 'Action',
            dataIndex: 'action_key',
            render: function RenderAction(_, changeRequest) {
                return (
                    <LemonTableLink
                        to={urls.approval(changeRequest.id)}
                        title={getApprovalActionLabel(changeRequest.action_key)}
                    />
                )
            },
        },
        {
            title: 'Resource',
            render: function RenderResource(_, changeRequest) {
                const resourceUrl = getApprovalResourceUrl(changeRequest.action_key, changeRequest.resource_id)
                const name = getApprovalResourceName(changeRequest.resource_type, changeRequest.intent)
                return resourceUrl && name ? <LemonTableLink to={resourceUrl} title={name} /> : name
            },
        },
        {
            title: 'Requested by',
            render: function RenderRequester(_, changeRequest) {
                return <ProfilePicture user={changeRequest.created_by} size="md" showName />
            },
        },
        {
            title: 'Status',
            dataIndex: 'state',
            render: function RenderStatus(_, changeRequest) {
                return <StatusTag state={changeRequest.state} />
            },
        },
        {
            title: 'Approvals',
            render: function RenderApprovals(_, changeRequest) {
                const required = changeRequest.policy_snapshot?.quorum || 1
                const current = changeRequest.approvals?.length || 0
                return (
                    <div>
                        {current} / {required}
                    </div>
                )
            },
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            render: function RenderCreatedAt(_, changeRequest) {
                return <TZLabel time={changeRequest.created_at} />
            },
        },
        {
            title: 'Expires',
            dataIndex: 'expires_at',
            render: function RenderExpiresAt(_, changeRequest) {
                if (changeRequest.state !== ChangeRequestState.Pending || !changeRequest.expires_at) {
                    return null
                }
                const expiresAt = dayjs(changeRequest.expires_at)
                const hoursLeft = expiresAt.diff(dayjs(), 'hours')

                if (hoursLeft < 0) {
                    return (
                        <span className="text-danger">
                            <TZLabel time={changeRequest.expires_at} />
                        </span>
                    )
                }
                if (hoursLeft < 24) {
                    return (
                        <span className="text-warning">
                            <TZLabel time={changeRequest.expires_at} />
                        </span>
                    )
                }
                return <TZLabel time={changeRequest.expires_at} />
            },
        },
        {
            width: 0,
            render: function RenderActions(_, changeRequest) {
                return (
                    <ChangeRequestTableActions
                        changeRequest={changeRequest}
                        onApprove={approveChangeRequest}
                        onReject={rejectChangeRequest}
                    />
                )
            },
        },
    ]

    return (
        <div className="space-y-4">
            <div className={cn('flex flex-wrap gap-2 justify-between')}>
                <div className="flex gap-2 items-center">
                    <span>
                        <b>Status</b>
                    </span>
                    <LemonSelect
                        dropdownMatchSelectWidth={false}
                        onChange={(value) => {
                            setFilters({ state: value || undefined })
                        }}
                        size="small"
                        options={[
                            { label: 'All', value: null },
                            { label: 'Pending', value: ChangeRequestState.Pending },
                            { label: 'Approved', value: ChangeRequestState.Approved },
                            { label: 'Applied', value: ChangeRequestState.Applied },
                            { label: 'Rejected', value: ChangeRequestState.Rejected },
                            { label: 'Expired', value: ChangeRequestState.Expired },
                            { label: 'Failed', value: ChangeRequestState.Failed },
                        ]}
                        value={filters.state ?? null}
                    />
                </div>
            </div>

            <LemonTable
                dataSource={changeRequests}
                columns={columns}
                rowKey="id"
                loading={changeRequestsDataLoading}
                nouns={['change request', 'change requests']}
                data-attr="approvals-table"
                emptyState="No change requests found"
                footer={
                    hasMore && (
                        <div className="flex justify-center p-1">
                            <LemonButton
                                onClick={loadMore}
                                className="min-w-full text-center"
                                disabledReason={changeRequestsDataLoading ? 'Loading change requests' : ''}
                            >
                                <span className="flex-1 text-center">
                                    {changeRequestsDataLoading ? 'Loading...' : 'Load more'}
                                </span>
                            </LemonButton>
                        </div>
                    )
                }
            />
        </div>
    )
}

function ChangeRequestTableActions({
    changeRequest,
    onApprove,
    onReject,
}: {
    changeRequest: ChangeRequest
    onApprove: (id: string) => void
    onReject: (id: string, reason: string) => void
}): JSX.Element {
    const { showApproveButton, showRejectButton } = getChangeRequestButtonVisibility(changeRequest)

    return (
        <More
            overlay={
                <>
                    <LemonButton fullWidth onClick={() => router.actions.push(urls.approval(changeRequest.id))}>
                        View details
                    </LemonButton>
                    {showApproveButton && (
                        <LemonButton
                            fullWidth
                            type="primary"
                            onClick={() => {
                                LemonDialog.open({
                                    title: 'Approve this change request?',
                                    content: (
                                        <div className="text-sm text-secondary">
                                            This will add your approval to the change request.
                                            {changeRequest.policy_snapshot?.quorum === 1
                                                ? ' The change will be applied automatically.'
                                                : ''}
                                        </div>
                                    ),
                                    primaryButton: {
                                        children: 'Approve',
                                        type: 'primary',
                                        onClick: () => onApprove(changeRequest.id),
                                        size: 'small',
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                        type: 'tertiary',
                                        size: 'small',
                                    },
                                })
                            }}
                        >
                            Approve
                        </LemonButton>
                    )}
                    {showRejectButton && (
                        <LemonButton
                            fullWidth
                            status="danger"
                            onClick={() => {
                                LemonDialog.open({
                                    title: 'Reject this change request?',
                                    content: (
                                        <div>
                                            <div className="text-sm text-secondary mb-2">
                                                This will reject the change request and prevent it from being applied.
                                            </div>
                                            <LemonInput
                                                id="reject-reason"
                                                placeholder="Reason for rejection (required)"
                                            />
                                        </div>
                                    ),
                                    primaryButton: {
                                        children: 'Reject',
                                        type: 'primary',
                                        status: 'danger',
                                        onClick: () => {
                                            const reason = (
                                                document.getElementById('reject-reason') as HTMLInputElement
                                            )?.value
                                            if (!reason) {
                                                lemonToast.error('Please provide a reason for rejection')
                                                return
                                            }
                                            onReject(changeRequest.id, reason)
                                        },
                                        size: 'small',
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                        type: 'tertiary',
                                        size: 'small',
                                    },
                                })
                            }}
                        >
                            Reject
                        </LemonButton>
                    )}
                </>
            }
        />
    )
}

function StatusTag({ state }: { state: ChangeRequestState }): JSX.Element {
    const tagTypes = {
        [ChangeRequestState.Pending]: 'default',
        [ChangeRequestState.Approved]: 'primary',
        [ChangeRequestState.Applied]: 'success',
        [ChangeRequestState.Rejected]: 'danger',
        [ChangeRequestState.Expired]: 'warning',
        [ChangeRequestState.Failed]: 'danger',
    } as const

    return (
        <LemonTag type={tagTypes[state]} className="uppercase">
            {state}
        </LemonTag>
    )
}
