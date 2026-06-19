import { connect, kea, key, listeners, path, props } from 'kea'

import { issueActionsLogic } from 'products/error_tracking/frontend/components/IssueActions/issueActionsLogic'

import type { WidgetIssueMetadataDelta } from './applyWidgetIssueMetadataChange'
import type { errorTrackingWidgetLogicType } from './errorTrackingWidgetLogicType'

export type ErrorTrackingWidgetLogicProps = {
    tileId: number
    onApplyIssueMetadataChange?: (issueId: string, delta: WidgetIssueMetadataDelta) => void
    onRefreshData?: () => void
}

const ISSUE_METADATA_MUTATIONS = new Set(['updateIssueStatus', 'updateIssueAssignee'])

export const errorTrackingWidgetLogic = kea<errorTrackingWidgetLogicType>([
    path(['products', 'dashboards', 'widgets', 'error_tracking', 'errorTrackingWidgetLogic']),
    key((props) => String(props.tileId)),

    props({
        tileId: 0,
        onApplyIssueMetadataChange: undefined,
        onRefreshData: undefined,
    } as ErrorTrackingWidgetLogicProps),

    connect({
        actions: [issueActionsLogic, ['updateIssueStatus', 'updateIssueAssignee', 'mutationFailure']],
    }),

    listeners(({ props }) => ({
        updateIssueStatus: ({ id, status }) => {
            props.onApplyIssueMetadataChange?.(id, { status })
        },
        updateIssueAssignee: ({ id, assignee }) => {
            props.onApplyIssueMetadataChange?.(id, { assignee })
        },
        mutationFailure: ({ mutationName }) => {
            if (!props.onRefreshData || !ISSUE_METADATA_MUTATIONS.has(mutationName)) {
                return
            }
            props.onRefreshData()
        },
    })),
])
