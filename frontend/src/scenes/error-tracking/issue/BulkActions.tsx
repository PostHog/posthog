import { LemonButton, LemonDialog } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { AssigneeSelect } from '../AssigneeSelect'
import { errorTrackingDataNodeLogic } from '../errorTrackingDataNodeLogic'
import { errorTrackingSceneLogic } from '../errorTrackingSceneLogic'
import { GenericSelect } from './GenericSelect'
import { IssueStatus, StatusIndicator } from './Indicator'

export function BulkActions(): JSX.Element {
    const { mergeIssues, assignIssues, resolveIssues, suppressIssues, activateIssues } =
        useActions(errorTrackingDataNodeLogic)
    const { selectedIssueIds } = useValues(errorTrackingSceneLogic)
    const { setSelectedIssueIds } = useActions(errorTrackingSceneLogic)
    const { results } = useValues(errorTrackingDataNodeLogic)

    const hasAtLeastOneIssue = selectedIssueIds.length > 0
    const hasAtLeastTwoIssues = selectedIssueIds.length >= 2

    const currentStatus = results
        .filter((issue: ErrorTrackingIssue) => selectedIssueIds.includes(issue.id))
        .map((issue: ErrorTrackingIssue) => issue.status as IssueStatus)
        .reduce<IssueStatus | 'mixed' | null>((acc, status) => {
            if (acc === null) {
                return status
            } else if (acc === 'mixed') {
                return 'mixed'
            } else if (acc !== status) {
                return 'mixed'
            }
            return acc
        }, null)

    return (
        <>
            {hasAtLeastOneIssue ? (
                <>
                    <LemonButton type="secondary" size="small" onClick={() => setSelectedIssueIds([])}>
                        Unselect all
                    </LemonButton>
                    <LemonButton
                        disabledReason={!hasAtLeastTwoIssues ? 'Select at least two issues to merge' : null}
                        type="secondary"
                        size="small"
                        onClick={() =>
                            LemonDialog.open({
                                title: 'Merge Issues',
                                content: `Are you sure you want to merge these ${selectedIssueIds.length} issues?`,
                                primaryButton: {
                                    children: 'Merge',
                                    status: 'danger',
                                    onClick: () => {
                                        mergeIssues(selectedIssueIds)
                                        setSelectedIssueIds([])
                                    },
                                },
                            })
                        }
                    >
                        Merge
                    </LemonButton>
                    <GenericSelect
                        size="small"
                        current={currentStatus == 'mixed' ? null : currentStatus}
                        values={['active', 'resolved', 'suppressed']}
                        placeholder="Mark as"
                        renderValue={(value) => {
                            return (
                                <StatusIndicator
                                    status={value as IssueStatus}
                                    size="small"
                                    className="w-full"
                                    withTooltip={true}
                                />
                            )
                        }}
                        onChange={(value) => {
                            if (value == currentStatus) {
                                return
                            }
                            switch (value) {
                                case 'resolved':
                                    resolveIssues(selectedIssueIds)
                                    setSelectedIssueIds([])
                                    break
                                case 'suppressed':
                                    suppressIssues(selectedIssueIds)
                                    setSelectedIssueIds([])
                                    break
                                case 'active':
                                    activateIssues(selectedIssueIds)
                                    setSelectedIssueIds([])
                                    break
                                default:
                                    break
                            }
                        }}
                    />
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
                    onClick={() => setSelectedIssueIds(results.map((issue: ErrorTrackingIssue) => issue.id))}
                >
                    Select all
                </LemonButton>
            )}
        </>
    )
}
