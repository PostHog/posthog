import { BindLogic, useActions, useValues } from 'kea'
import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture/ProfileBubbles'
import { metalyticsLogic } from 'lib/components/Metalytics/metalyticsLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { hogql } from '~/queries/utils'

export function SidePanelActivityMetalytics(): JSX.Element {
    const { instanceId, viewCount, recentUserMembers } = useValues(metalyticsLogic)

    if (!instanceId) {
        return (
            <>
                <h3>Metalytics</h3>
                <p>
                    You can see internal analytics of how your Organization members are using PostHog for certain
                    things.
                </p>
            </>
        )
    }
    return (
        <>
            <div className="mb-4 rounded bg-bg-light p-4">
                <div className="text-muted text-sm">Total Views</div>
                <div className="text-2xl font-semibold">{viewCount ?? 0}</div>
            </div>

            {/* This looks odd but is a weirdness of the Query component it needs to be bound in an insight logic */}
            <BindLogic logic={insightLogic} props={{ dashboardItemId: '', doNotLoad: true }}>
                <Query
                    query={{
                        display: 'ActionsLineGraph',
                        chartSettings: {
                            seriesBreakdownColumn: null,
                        },
                        kind: NodeKind.DataVisualizationNode,
                        source: {
                            kind: NodeKind.HogQLQuery,
                            query: hogql`SELECT sum(count) as count
                FROM app_metrics
                WHERE app_source = 'metalytics'
                AND instance_id = ${instanceId}`,
                        },
                    }}
                />
            </BindLogic>
        </>
    )
}
