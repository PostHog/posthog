import { useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonTag, Link } from '@posthog/lemon-ui'

import { getDefaultEventsSceneQuery } from 'scenes/activity/explore/defaults'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ConversionGoalFilter, NodeKind } from '~/queries/schema/schema-general'
import { ActivityTab, PropertyFilterType, PropertyOperator } from '~/types'

export function ConversionGoalDetails({ goal }: { goal: ConversionGoalFilter }): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const event = goal.kind === NodeKind.EventsNode ? goal.event : undefined
    const query = getDefaultEventsSceneQuery([
        { type: PropertyFilterType.EventMetadata, key: 'event', value: event, operator: PropertyOperator.Exact },
    ])
    const eventUrl = combineUrl(
        `/project/${currentTeamId}${urls.activity(ActivityTab.ExploreEvents)}`,
        {},
        {
            q: { ...query, source: { ...query.source, after: '-30d' } },
        }
    ).url
    return (
        <div className="flex flex-col gap-1 text-xs">
            <div className="flex flex-wrap gap-1">
                {goal.counts_as_revenue && <LemonTag type="success">Revenue</LemonTag>}
                {goal.counts_as_customer && <LemonTag>Customer</LemonTag>}
                {!goal.counts_as_revenue && !goal.counts_as_customer && <LemonTag type="muted">Conversion</LemonTag>}
            </div>
            {event && (
                <span>
                    Event:{' '}
                    <Link to={eventUrl} target="_blank">
                        {event}
                    </Link>
                </span>
            )}
            {goal.counts_as_revenue && (
                <span>
                    Amount property: <code>{goal.math_property}</code> · Sum
                    {goal.math_property_revenue_currency ? ` · ${goal.math_property_revenue_currency}` : ''}
                </span>
            )}
            <span className="text-secondary">
                Open the event to inspect individual occurrences and their properties.
            </span>
            {goal.properties && Object.keys(goal.properties).length > 0 && (
                <details>
                    <summary>Goal property filters</summary>
                    <pre className="whitespace-pre-wrap break-all">{JSON.stringify(goal.properties, null, 2)}</pre>
                </details>
            )}
        </div>
    )
}
