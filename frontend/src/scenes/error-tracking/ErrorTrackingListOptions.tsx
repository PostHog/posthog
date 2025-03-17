import { LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { AssigneeSelect } from './AssigneeSelect'
import { errorTrackingDataNodeLogic } from './errorTrackingDataNodeLogic'
import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'
import { BulkActions } from './issue/BulkActions'
import { GenericSelect } from './issue/StatusSelect'
import { IndicatorTag, StatusTag } from './issue/StatusTag'

export const ErrorTrackingListOptions = (): JSX.Element => {
    const { assignee } = useValues(errorTrackingLogic)
    const { setAssignee } = useActions(errorTrackingLogic)
    const { orderBy, status, orderDirection } = useValues(errorTrackingSceneLogic)
    const { setOrderBy, setStatus, setOrderDirection } = useActions(errorTrackingSceneLogic)
    const { results } = useValues(errorTrackingDataNodeLogic)

    const { selectedIssueIds } = useValues(errorTrackingSceneLogic)
    const { setSelectedIssueIds } = useActions(errorTrackingSceneLogic)
    const { mergeIssues, assignIssues, resolveIssues, suppressIssues, activateIssues } =
        useActions(errorTrackingDataNodeLogic)
    const selectedIssues = useMemo(
        () => results.filter((issue) => selectedIssueIds.includes(issue.id)),
        [results, selectedIssueIds]
    )
    return (
        <>
            <div className="sticky top-[var(--breadcrumbs-height-compact)] z-20 py-2 bg-primary flex justify-between">
                <div className="flex deprecated-space-x-2">
                    <BulkActions
                        onMerge={mergeIssues}
                        onAssign={assignIssues}
                        onSuppress={suppressIssues}
                        onActivate={activateIssues}
                        onResolve={resolveIssues}
                        issueSelection={selectedIssues}
                        onSelectAll={() => setSelectedIssueIds(results.map((issue) => issue.id))}
                        onClearSelection={() => setSelectedIssueIds([])}
                    />
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
                                        return <IndicatorTag intent="key" label="All" size="small" />
                                    default:
                                        return <StatusTag status={key} size="small" />
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
