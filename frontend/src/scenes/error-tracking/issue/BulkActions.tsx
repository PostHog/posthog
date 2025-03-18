import { LemonButton } from '@posthog/lemon-ui'
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
        .map((issue: ErrorTrackingIssue) => issue.status as IssueStatus)
        .reduce<IssueStatus | undefined | null>((acc, status) => {
            if (acc === null) {
                return status
            }
            if (acc === undefined) {
                return undefined
            }
            if (acc !== status) {
                return undefined
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
                        onClick={() => {
                            mergeIssues(selectedIssueIds)
                            setSelectedIssueIds([])
                        }}
                    >
                        Merge
                    </LemonButton>
                    <GenericSelect
                        size="small"
                        current={undefined}
                        values={['active', 'resolved', 'suppressed'].filter((status) => status !== currentStatus)}
                        placeholder="Mark as"
                        renderValue={(value) => {
                            return <StatusIndicator status={value as IssueStatus} size="small" withTooltip={true} />
                        }}
                        onChange={(value) => {
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
