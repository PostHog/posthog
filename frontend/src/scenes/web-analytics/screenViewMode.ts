import { EventsNode, HogQLQueryModifiers } from '~/queries/schema/schema-general'
import { PropertyFilterType } from '~/types'

export type WebAnalyticsScreenViewMode = NonNullable<HogQLQueryModifiers['webAnalyticsScreenViewMode']>

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
