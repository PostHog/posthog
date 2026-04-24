import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonTable, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import type { LimitIncreaseRequestPayload } from 'lib/components/LimitExceededModal/limitExceededLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { teamLogic } from 'scenes/teamLogic'

import { limitRequestsLogic } from './limitRequestsLogic'

const STATUS_COLOR: Record<LimitIncreaseRequestPayload['status'], 'warning' | 'success' | 'danger'> = {
    pending: 'warning',
    approved: 'success',
    denied: 'danger',
}

function ExpandedRow({ request }: { request: LimitIncreaseRequestPayload }): JSX.Element {
    const { savingId } = useValues(limitRequestsLogic)
    const { saveJustification } = useActions(limitRequestsLogic)
    const [draft, setDraft] = useState(request.justification ?? '')

    useEffect(() => {
        setDraft(request.justification ?? '')
    }, [request.justification])

    const dirty = draft !== (request.justification ?? '')
    const saving = savingId === request.id

    if (request.status !== 'pending') {
        return (
            <div className="p-4 flex flex-col gap-2">
                <h4 className="m-0 text-sm font-semibold">Your context</h4>
                <p className="m-0">
                    {request.justification || <span className="text-muted italic">You didn't add any context.</span>}
                </p>
                {request.resolution_note ? (
                    <>
                        <h4 className="m-0 text-sm font-semibold mt-2">Our note</h4>
                        <p className="m-0 text-muted">{request.resolution_note}</p>
                    </>
                ) : null}
            </div>
        )
    }

    return (
        <div className="p-4 flex flex-col gap-3">
            <h4 className="m-0 text-sm font-semibold">Add context to help us approve this faster</h4>
            <LemonTextArea
                value={draft}
                onChange={setDraft}
                minRows={4}
                placeholder="e.g. every one of our 200 customers gets their own dashboard, yes really"
            />
            <div className="flex justify-end gap-2">
                <LemonButton
                    type="tertiary"
                    onClick={() => setDraft(request.justification ?? '')}
                    disabledReason={!dirty ? 'No changes' : undefined}
                >
                    Reset
                </LemonButton>
                <LemonButton
                    type="primary"
                    loading={saving}
                    disabledReason={!dirty ? 'No changes to save' : undefined}
                    onClick={() => saveJustification(request.id, draft)}
                >
                    Save context
                </LemonButton>
            </div>
        </div>
    )
}

export function LimitRequests(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { requests, requestsLoading, expandedIds } = useValues(limitRequestsLogic)
    const { loadRequests, setProjectId, toggleExpanded } = useActions(limitRequestsLogic)

    useEffect(() => {
        if (currentTeamId) {
            setProjectId(currentTeamId)
            loadRequests(currentTeamId)
        }
    }, [currentTeamId, loadRequests, setProjectId])

    return (
        <div className="flex flex-col gap-3">
            <p className="m-0 text-muted">
                Limit increase requests are submitted automatically when this project hits a resource limit. Click a row
                to add context, it helps our team approve it faster.
            </p>
            <LemonTable<LimitIncreaseRequestPayload>
                dataSource={requests}
                loading={requestsLoading}
                rowKey="id"
                expandable={{
                    expandedRowRender: (request) => <ExpandedRow request={request} />,
                    rowExpandable: () => true,
                    isRowExpanded: (request) => (expandedIds.includes(request.id) ? 1 : 0),
                    onRowExpand: (request) => toggleExpanded(request.id),
                    onRowCollapse: (request) => toggleExpanded(request.id),
                }}
                onRow={(request) => ({
                    onClick: (e) => {
                        if ((e.target as HTMLElement).closest('.LemonTable__toggle')) {
                            return
                        }
                        toggleExpanded(request.id)
                    },
                    style: { cursor: 'pointer' },
                })}
                columns={[
                    {
                        title: 'Limit',
                        dataIndex: 'limit_description',
                        render: (_, request) => request.limit_description || request.limit_key,
                    },
                    {
                        title: 'Limit at hit',
                        dataIndex: 'limit_at_first_hit',
                        render: (_, request) => request.limit_at_first_hit.toLocaleString(),
                    },
                    {
                        title: 'Granted',
                        dataIndex: 'granted_value',
                        render: (_, request) => {
                            if (request.status !== 'approved') {
                                return <span className="text-muted">—</span>
                            }
                            return request.granted_value === null ? 'Unlimited' : request.granted_value.toLocaleString()
                        },
                    },
                    {
                        title: 'Status',
                        dataIndex: 'status',
                        render: (_, request) => (
                            <LemonTag type={STATUS_COLOR[request.status]}>{request.status}</LemonTag>
                        ),
                    },
                    {
                        title: 'Last hit',
                        dataIndex: 'last_hit_at',
                        render: (_, request) => <TZLabel time={request.last_hit_at} />,
                    },
                    {
                        title: 'Context',
                        render: (_, request) => (
                            <div className="max-w-md truncate text-muted">
                                {request.justification || <span className="italic">None yet</span>}
                            </div>
                        ),
                    },
                ]}
                emptyState="No limit increase requests yet. You'll see them here if this project hits a resource limit."
            />
        </div>
    )
}
