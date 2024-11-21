import { BindLogic, useValues } from 'kea'
import { metalyticsLogic } from 'lib/components/Metalytics/metalyticsLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { hogql } from '~/queries/utils'

export function SidePanelActivityMetalytics(): JSX.Element {
    const { instanceId } = useValues(metalyticsLogic)

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
