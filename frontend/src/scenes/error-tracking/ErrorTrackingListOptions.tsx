import { LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { AssigneeSelect } from './AssigneeSelect'
import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'

export const ErrorTrackingListOptions = (): JSX.Element => {
    const { assignee } = useValues(errorTrackingLogic)
    const { setAssignee } = useActions(errorTrackingLogic)
    const { orderBy, status } = useValues(errorTrackingSceneLogic)
    const { setOrderBy, setStatus } = useActions(errorTrackingSceneLogic)

    return (
        <div className="flex justify-end space-x-2 py-2">
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
        </div>
    )
}
