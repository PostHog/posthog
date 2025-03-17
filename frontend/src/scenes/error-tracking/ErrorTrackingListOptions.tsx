import { LemonButton, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { AssigneeSelect } from './AssigneeSelect'
import { errorTrackingDataNodeLogic } from './errorTrackingDataNodeLogic'
import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'

export const ErrorTrackingListOptions = (): JSX.Element => {
    const { assignee } = useValues(errorTrackingLogic)
    const { setAssignee } = useActions(errorTrackingLogic)
    const { orderBy, status, orderDirection } = useValues(errorTrackingSceneLogic)
    const { setOrderBy, setStatus, setOrderDirection } = useActions(errorTrackingSceneLogic)
    const { results } = useValues(errorTrackingDataNodeLogic)

    const { selectedIssueIds } = useValues(errorTrackingSceneLogic)
    const { setSelectedIssueIds } = useActions(errorTrackingSceneLogic)
    const { mergeIssues, assignIssues, resolveIssues, suppressIssues } = useActions(errorTrackingDataNodeLogic)

    return (
        <>
            <div className="sticky top-[var(--breadcrumbs-height-compact)] z-20 py-2 bg-primary flex justify-between">
                <div className="flex deprecated-space-x-2">
                    {selectedIssueIds.length > 0 ? (
                        <>
                            <LemonButton type="secondary" size="small" onClick={() => setSelectedIssueIds([])}>
                                Unselect all
                            </LemonButton>
                            <LemonButton
                                disabledReason={
                                    selectedIssueIds.length < 2 ? 'Select at least two issues to merge' : null
                                }
                                type="secondary"
                                size="small"
                                onClick={() => {
                                    mergeIssues(selectedIssueIds)
                                    setSelectedIssueIds([])
                                }}
                            >
                                Merge
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => {
                                    resolveIssues(selectedIssueIds)
                                    setSelectedIssueIds([])
                                }}
                            >
                                Resolve
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                size="small"
                                status="danger"
                                tooltip="Stop capturing these errors"
                                onClick={() => {
                                    suppressIssues(selectedIssueIds)
                                    setSelectedIssueIds([])
                                }}
                            >
                                Suppress
                            </LemonButton>
                            <AssigneeSelect
                                type="secondary"
                                size="small"
                                showName
                                showIcon={false}
                                unassignedLabel="Assign"
                                assignee={null}
                                onChange={(assignee) => assignIssues(selectedIssueIds, assignee)}
                            />
                        </>
                    ) : (
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => setSelectedIssueIds(results.map((issue) => issue.id))}
                        >
                            Select all
                        </LemonButton>
                    )}
                </div>
                {selectedIssueIds.length < 1 && (
                    <span className="flex deprecated-space-x-2">
                        <div className="flex items-center gap-1">
                            <span>Status:</span>
                            <LemonSelect
                                onSelect={setStatus}
                                onChange={setStatus}
                                value={status}
                                options={[
                                    {
                                        value: 'all',
                                        label: 'All',
                                    },
                                    {
                                        value: 'active',
                                        label: 'Active',
                                    },
                                    {
                                        value: 'resolved',
                                        label: 'Resolved',
                                    },
                                    {
                                        value: 'suppressed',
                                        label: 'Suppressed',
                                    },
                                ]}
                                size="small"
                            />
                        </div>
                        <div className="flex items-center gap-1">
                            <span>Sort by:</span>
                            <LemonSelect
                                onSelect={setOrderBy}
                                onChange={setOrderBy}
                                value={orderBy}
                                options={[
                                    {
                                        value: 'last_seen',
                                        label: 'Last seen',
                                    },
                                    {
                                        value: 'first_seen',
                                        label: 'First seen',
                                    },
                                    {
                                        value: 'occurrences',
                                        label: 'Occurrences',
                                    },
                                    {
                                        value: 'users',
                                        label: 'Users',
                                    },
                                    {
                                        value: 'sessions',
                                        label: 'Sessions',
                                    },
                                ]}
                                size="small"
                            />
                            <LemonSelect
                                onSelect={setOrderDirection}
                                onChange={setOrderDirection}
                                value={orderDirection}
                                options={[
                                    {
                                        value: 'DESC',
                                        label: 'Descending',
                                    },
                                    {
                                        value: 'ASC',
                                        label: 'Ascending',
                                    },
                                ]}
                                size="small"
                            />
                        </div>
                        <div className="flex items-center gap-1">
                            <span>Assigned to:</span>
                            <AssigneeSelect
                                showName
                                showIcon={false}
                                assignee={assignee}
                                onChange={(assignee) => setAssignee(assignee)}
                                unassignedLabel="Any user"
                                type="secondary"
                                size="small"
                            />
                        </div>
                    </span>
                )}
            </div>
        </>
    )
}
