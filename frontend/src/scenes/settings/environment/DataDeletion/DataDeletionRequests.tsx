import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import { type DataDeletionRequestApi, RequestStatusEnumApi } from '~/generated/core/api.schemas'

import { dataDeletionRequestsLogic } from './dataDeletionRequestsLogic'
import { QuillDataDeletionRequests } from './QuillDataDeletionRequests'

const STATUS_DISPLAY: Record<RequestStatusEnumApi, { label: string; type: LemonTagType; description: string }> = {
    [RequestStatusEnumApi.Draft]: {
        label: 'Draft',
        type: 'muted',
        description: 'This request is not submitted yet.',
    },
    [RequestStatusEnumApi.Pending]: {
        label: 'In review',
        type: 'default',
        description: 'PostHog reviews every request before any events are deleted.',
    },
    [RequestStatusEnumApi.Approved]: {
        label: 'Approved',
        type: 'primary',
        description: 'PostHog approved this request and will select the matching events next.',
    },
    [RequestStatusEnumApi.InProgress]: {
        label: 'Selecting events',
        type: 'primary',
        description: 'PostHog is selecting the events that match the query.',
    },
    [RequestStatusEnumApi.Queued]: {
        label: 'Queued for deletion',
        type: 'warning',
        description: 'The matching events are deleted in the next weekend deletion window.',
    },
    [RequestStatusEnumApi.Completed]: {
        label: 'Completed',
        type: 'success',
        description: 'The matching events are deleted.',
    },
    [RequestStatusEnumApi.Failed]: {
        label: 'Failed',
        type: 'danger',
        description: 'This request failed. Contact support to retry it.',
    },
}

export function DataDeletionRequests(): JSX.Element {
    const { dataDeletionRequests, dataDeletionRequestsLoading, loadFailed, newRequestDisabledReason } =
        useValues(dataDeletionRequestsLogic)
    const { loadDataDeletionRequests } = useActions(dataDeletionRequestsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const newRequestButtonDisabledReason = loadFailed ? 'Could not load deletion requests' : newRequestDisabledReason

    if (todayRailNav) {
        return (
            <QuillDataDeletionRequests
                requests={dataDeletionRequests}
                loading={dataDeletionRequestsLoading}
                loadFailed={loadFailed}
                onRetry={() => loadDataDeletionRequests()}
                newRequestDisabledReason={newRequestButtonDisabledReason}
                getStatus={(request) => STATUS_DISPLAY[request.status]}
            />
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <LemonButton
                type="primary"
                icon={<IconPlus />}
                className="self-start"
                to={urls.dataDeletionRequestNew()}
                disabledReason={newRequestButtonDisabledReason}
                data-attr="data-deletion-new-request"
            >
                New deletion request
            </LemonButton>
            {loadFailed ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadDataDeletionRequests() }}>
                    Could not load deletion requests. Try again, and contact support if it keeps happening.
                </LemonBanner>
            ) : (
                <LemonTable<DataDeletionRequestApi>
                    dataSource={dataDeletionRequests ?? []}
                    loading={dataDeletionRequestsLoading}
                    rowKey="id"
                    columns={[
                        {
                            title: 'Status',
                            dataIndex: 'status',
                            render: (_, request) => {
                                const status = STATUS_DISPLAY[request.status]
                                return (
                                    <Tooltip title={status.description}>
                                        <LemonTag type={status.type}>{status.label}</LemonTag>
                                    </Tooltip>
                                )
                            },
                        },
                        {
                            title: 'Submitted',
                            dataIndex: 'created_at',
                            render: (_, request) => <TZLabel time={request.created_at} />,
                        },
                        {
                            title: 'Approved',
                            dataIndex: 'approved_at',
                            render: (_, request) =>
                                request.approved_at ? (
                                    <TZLabel time={request.approved_at} />
                                ) : (
                                    <span className="text-secondary">Not yet</span>
                                ),
                        },
                    ]}
                    expandable={{
                        expandedRowRender: (request) => (
                            <div className="p-2">
                                <CodeSnippet language={Language.SQL} wrap>
                                    {request.query}
                                </CodeSnippet>
                            </div>
                        ),
                    }}
                    emptyState="No deletion requests yet. Submitted requests appear here with their status."
                />
            )}
        </div>
    )
}
