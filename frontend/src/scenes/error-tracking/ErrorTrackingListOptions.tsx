import { LemonButton, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { AssigneeLabelDisplay } from './components/Assignee/AssigneeDisplay'
import { AssigneeSelect } from './components/Assignee/AssigneeSelect'
import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'
import { BulkActions } from './issue/BulkActions'
import { GenericSelect } from './issue/GenericSelect'
import { LabelIndicator, StatusIndicator } from './issue/Indicator'

export const ErrorTrackingListOptions = (): JSX.Element => {
    const { assignee } = useValues(errorTrackingLogic)
    const { setAssignee } = useActions(errorTrackingLogic)
    const { orderBy, status, orderDirection } = useValues(errorTrackingSceneLogic)
    const { setOrderBy, setStatus, setOrderDirection } = useActions(errorTrackingSceneLogic)
    const { selectedIssueIds } = useValues(errorTrackingSceneLogic)

    return (
        <>
            <div className="sticky top-[var(--breadcrumbs-height-compact)] z-20 py-2 bg-primary flex justify-between">
                <div className="flex deprecated-space-x-2">
                    <BulkActions />
                </div>
                {selectedIssueIds.length < 1 && (
                    <span className="flex deprecated-space-x-2">
                        <GenericSelect<ErrorTrackingIssue['status'] | 'all' | null>
                            values={['all', 'active', 'resolved', 'suppressed']}
                            current={status || null}
                            renderValue={(key) => {
                                switch (key) {
                                    case 'all':
                                    case null:
                                        return <LabelIndicator intent="muted" label="All" size="small" />
                                    default:
                                        return <StatusIndicator status={key} size="small" />
                                }
                            }}
                            placeholder="Select status"
                            onChange={(value) => setStatus(value || undefined)}
                            size="small"
                        />
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
                            <AssigneeSelect assignee={assignee} onChange={(assignee) => setAssignee(assignee)}>
                                {(displayAssignee) => (
                                    <LemonButton type="secondary" size="small">
                                        <AssigneeLabelDisplay assignee={displayAssignee} placeholder="Any user" />
                                    </LemonButton>
                                )}
                            </AssigneeSelect>
                        </div>
                    </span>
                )}
            </div>
        </>
    )
}
