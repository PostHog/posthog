import { LemonButton, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { AssigneeSelect } from './AssigneeSelect'
import { errorTrackingDataNodeLogic } from './errorTrackingDataNodeLogic'
import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'

export const ErrorTrackingListOptions = (): JSX.Element => {
    const { assignee } = useValues(errorTrackingLogic)
    const { setAssignee } = useActions(errorTrackingLogic)
    const { orderBy, status } = useValues(errorTrackingSceneLogic)
    const { setOrderBy, setStatus } = useActions(errorTrackingSceneLogic)

    const { selectedIssueIds } = useValues(errorTrackingSceneLogic)
    const { setSelectedIssueIds } = useActions(errorTrackingSceneLogic)
    const { mergeIssues } = useActions(errorTrackingDataNodeLogic)

    return (
        <>
            <div className="sticky top-[var(--breadcrumbs-height-compact)] z-20 py-2 bg-primary flex justify-between">
                <div className="flex space-x-2">
                    <LemonButton
                        disabledReason={selectedIssueIds.length < 2 ? 'Select at least two issues to merge' : null}
                        type="secondary"
                        size="small"
                        onClick={() => {
                            mergeIssues(selectedIssueIds)
                            setSelectedIssueIds([])
                        }}
                    >
                        Merge Issues
                    </LemonButton>
                    {selectedIssueIds.length > 0 && (
                        <LemonButton type="secondary" size="small" onClick={() => setSelectedIssueIds([])}>
                            Unselect all
                        </LemonButton>
                    )}
                </div>
                {selectedIssueIds.length < 1 && (
                    <span className="flex space-x-2">
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
