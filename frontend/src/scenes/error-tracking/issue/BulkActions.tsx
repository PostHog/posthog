import { LemonButton } from '@posthog/lemon-ui'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { AssigneeSelect } from '../AssigneeSelect'
import { GenericSelect } from './StatusSelect'
import { IssueStatus, StatusTag } from './StatusTag'

export interface BulkActionsProps {
    issueSelection: ErrorTrackingIssue[]
    onAssign: (issueIds: string[], assigneeId: ErrorTrackingIssue['assignee']) => void
    onMerge: (issueIds: string[]) => void
    onResolve: (issueIds: string[]) => void
    onSuppress: (issueIds: string[]) => void
    onActivate: (issueIds: string[]) => void
    onSelectAll: () => void
    onClearSelection: () => void
}

export function BulkActions({
    onMerge,
    onResolve,
    onSuppress,
    onActivate,
    onAssign,
    issueSelection,
    onSelectAll,
    onClearSelection,
}: BulkActionsProps): JSX.Element {
    const hasAtLeastOneIssue = issueSelection.length > 0
    const hasAtLeastTwoIssues = issueSelection.length >= 2
    const selectedIssueIds = issueSelection.map((issue) => issue.id)
    const currentStatus = issueSelection
        .map((issue) => issue.status)
        .reduce<string | undefined | null>((acc, status) => {
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
                    <LemonButton type="secondary" size="small" onClick={() => onClearSelection()}>
                        Unselect all
                    </LemonButton>
                    <LemonButton
                        disabledReason={!hasAtLeastTwoIssues ? 'Select at least two issues to merge' : null}
                        type="secondary"
                        size="small"
                        onClick={() => {
                            onMerge(selectedIssueIds)
                            onClearSelection()
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
                            return <StatusTag status={value as IssueStatus} size="small" />
                        }}
                        onChange={(value) => {
                            switch (value) {
                                case 'resolved':
                                    onResolve(selectedIssueIds)
                                    onClearSelection()
                                    break
                                case 'suppressed':
                                    onSuppress(selectedIssueIds)
                                    onClearSelection()
                                    break
                                case 'active':
                                    onActivate(selectedIssueIds)
                                    onClearSelection()
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
                        onChange={(assignee) => onAssign(selectedIssueIds, assignee)}
                    />
                </>
            ) : (
                <LemonButton type="secondary" size="small" onClick={() => onSelectAll()}>
                    Select all
                </LemonButton>
            )}
        </>
    )
}
