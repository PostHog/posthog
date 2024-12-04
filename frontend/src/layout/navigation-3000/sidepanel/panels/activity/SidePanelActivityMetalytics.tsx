import { Tooltip } from '@posthog/lemon-ui'
import { BindLogic, useValues } from 'kea'
import { metalyticsLogic } from 'lib/components/Metalytics/metalyticsLogic'
import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture/ProfileBubbles'
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
        <div className="space-y-4 ">
            <div className="flex flex-wrap gap-4">
                <Tooltip
                    title="The total number of times this scene has been viewed by members of your organization."
                    placement="top"
                >
                    <div className="flex-1 p-4 border rounded bg-bg-light min-w-40">
                        <div className="text-sm text-muted">View count</div>
                        <div className="text-2xl font-semibold">{viewCount?.views ?? 0}</div>
                    </div>
                </Tooltip>

                <Tooltip
                    title="The total number of unique organization members who have viewed this scene."
                    placement="top"
                >
                    <div className="flex-1 p-4 border rounded bg-bg-light min-w-40">
                        <div className="text-sm text-muted">Viewer count</div>
                        <div className="text-2xl font-semibold">{viewCount?.users ?? 0}</div>
                    </div>
                </Tooltip>

                <Tooltip title="The most recent 30 users who have viewed this scene." placement="top">
                    <div className="flex-1 p-4 border rounded bg-bg-light min-w-40">
                        <div className="text-sm text-muted">Recent viewers (30 days)</div>
                        <ProfileBubbles
                            className="mt-2"
                            people={recentUserMembers.map((member) => ({
                                email: member.user.email,
                                name: member.user.first_name,
                                title: member.user.email,
                            }))}
                            limit={3}
                        />
                    </div>
                </Tooltip>
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
                            query: hogql`SELECT timestamp, SUM(count) AS number_of_sessions
                                FROM app_metrics
                                WHERE app_source = 'metalytics'
                                AND instance_id = ${instanceId}
                                AND timestamp >= NOW() - INTERVAL 30 DAY
                                GROUP BY timestamp
                                ORDER BY timestamp DESC`,
                        },
                    }}
                />
            </BindLogic>
        </div>
    )
}
