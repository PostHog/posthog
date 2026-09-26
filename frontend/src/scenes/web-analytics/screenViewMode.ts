import { EventsNode, HogQLQueryModifiers } from '~/queries/schema/schema-general'
import { PropertyFilterType } from '~/types'

export type WebAnalyticsScreenViewMode = NonNullable<HogQLQueryModifiers['webAnalyticsScreenViewMode']>

export function resolveScreenViewMode(
    teamModifiers: HogQLQueryModifiers | undefined,
    mobileFlagEnabled: boolean
): WebAnalyticsScreenViewMode | null {
    // The mobile flag predates the project setting and still means "screens only" for projects that have it.
    return teamModifiers?.webAnalyticsScreenViewMode ?? (mobileFlagEnabled ? 'screens' : null)
}

export function viewSeriesEvent(mode: WebAnalyticsScreenViewMode | null): Pick<EventsNode, 'event' | 'properties'> {
    if (mode === 'screens') {
        return { event: '$screen' }
    }
    if (mode === 'pageviews_and_screens') {
        return {
            event: null,
            properties: [{ type: PropertyFilterType.HogQL, key: "event IN ('$pageview', '$screen')" }],
        }
    }
    return { event: '$pageview' }
}
