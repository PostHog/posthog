import { useActions, useValues } from 'kea'

import { LemonLabel, LemonSwitch } from '@posthog/lemon-ui'

import { ActionsNode, DataWarehouseNode, EventsNode, NodeKind } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { insightVizDataLogic } from '../insightVizDataLogic'
import { sessionLevelAggregationFilterLogic } from './sessionLevelAggregationFilterLogic'

interface SessionLevelAggregationFilterProps {
    insightProps: InsightLogicProps
}

export function SessionLevelAggregationFilter({
    insightProps,
}: SessionLevelAggregationFilterProps): JSX.Element | null {
    const { querySource } = useValues(insightVizDataLogic(insightProps))
    const { sessionLevelAggregation } = useValues(sessionLevelAggregationFilterLogic(insightProps))
    const { setSessionLevelAggregation } = useActions(sessionLevelAggregationFilterLogic(insightProps))

    // Only show this option when using session properties as math_property in a trends query
    const isUsingSessionProperty =
        querySource?.kind === NodeKind.TrendsQuery &&
        querySource?.series?.some(
            (series: EventsNode | ActionsNode | DataWarehouseNode) => series.math_property_type === 'session_properties'
        )

    if (!isUsingSessionProperty) {
        return null
    }

    return (
        <>
            <div className="flex items-center gap-1">
                <LemonLabel
                    info="When using session properties, group events by session_id first before aggregating. This enables accurate bounce rate and session-based metrics by ensuring each session is counted once."
                    infoLink="https://posthog.com/docs/data/sessions"
                >
                    Aggregate at session level
                </LemonLabel>
                <LemonSwitch
                    className="m-2"
                    onChange={(checked) => {
                        setSessionLevelAggregation(checked)
                    }}
                    checked={!!sessionLevelAggregation}
                />
            </div>
        </>
    )
}
