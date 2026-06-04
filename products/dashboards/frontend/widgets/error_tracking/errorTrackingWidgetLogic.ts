import { connect, kea, listeners, path, props } from 'kea'

import { issueActionsLogic } from 'products/error_tracking/frontend/components/IssueActions/issueActionsLogic'

export type ErrorTrackingWidgetLogicProps = {
    onRefreshData?: () => void
}

const ISSUE_METADATA_MUTATIONS_REFRESHING_TILE = new Set(['updateIssueStatus', 'updateIssueAssignee'])

export const errorTrackingWidgetLogic = kea([
    path(['products', 'dashboards', 'widgets', 'error_tracking', 'errorTrackingWidgetLogic']),

    props({
        onRefreshData: undefined,
    } as ErrorTrackingWidgetLogicProps),

    connect({
        actions: [issueActionsLogic, ['mutationSuccess']],
    }),

    listeners(({ props }) => ({
        [issueActionsLogic.actionTypes.mutationSuccess]: ({ mutationName }: { mutationName: string }) => {
            if (!props.onRefreshData || !ISSUE_METADATA_MUTATIONS_REFRESHING_TILE.has(mutationName)) {
                return
            }
            props.onRefreshData()
        },
    })),
])
