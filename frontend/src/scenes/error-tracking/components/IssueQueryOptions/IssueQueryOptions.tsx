import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSelect, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { errorTrackingDataNodeLogic } from 'scenes/error-tracking/errorTrackingDataNodeLogic'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { AssigneeLabelDisplay } from '../Assignee/AssigneeDisplay'
import { AssigneeSelect } from '../Assignee/AssigneeSelect'
import { GenericSelect } from '../GenericSelect'
import { LabelIndicator, StatusIndicator } from '../Indicator'
import { issueQueryOptionsLogic } from './issueQueryOptionsLogic'

export const IssueQueryOptions = (): JSX.Element => {
    const { assignee, orderBy, status, orderDirection } = useValues(issueQueryOptionsLogic)
    const { setAssignee, setOrderBy, setStatus, setOrderDirection } = useActions(issueQueryOptionsLogic)

    return (
        <span className="flex items-center justify-between gap-2 self-end">
            <Reload />
            <div className="flex items-center gap-2 self-end">
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
                    <AssigneeSelect assignee={assignee ?? null} onChange={(assignee) => setAssignee(assignee)}>
                        {(displayAssignee) => (
                            <LemonButton type="secondary" size="small">
                                <AssigneeLabelDisplay assignee={displayAssignee} placeholder="Any user" />
                            </LemonButton>
                        )}
                    </AssigneeSelect>
                </div>
            </div>
        </span>
    )
}

const Reload = (): JSX.Element => {
    const { responseLoading } = useValues(errorTrackingDataNodeLogic)
    const { reloadData, cancelQuery } = useActions(errorTrackingDataNodeLogic)

    return (
        <LemonButton
            type="secondary"
            size="small"
            onClick={() => {
                if (responseLoading) {
                    cancelQuery()
                } else {
                    reloadData()
                }
            }}
            icon={responseLoading ? <Spinner textColored /> : <IconRefresh />}
        >
            {responseLoading ? 'Cancel' : 'Reload'}
        </LemonButton>
    )
}
