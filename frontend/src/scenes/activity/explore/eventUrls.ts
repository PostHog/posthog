import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { ActivityTab, PropertyFilterType, PropertyOperator } from '~/types'

import { getDefaultEventsSceneQuery } from './defaults'

/**
 * Event search scoped to one distinct ID. Safe to link to for any distinct ID, unlike a person
 * page — plenty of distinct IDs never get a person row (anonymous visitors under the SDK's
 * `identified_only` default, or events dropped before person processing). The default columns
 * include the person, `$lib` and the URL, and the person page stays one click away from any row.
 */
export const urlForEventsByDistinctId = (distinctId: string, after: string = '-30d'): string => {
    const query = getDefaultEventsSceneQuery([
        {
            type: PropertyFilterType.EventMetadata,
            key: 'distinct_id',
            value: distinctId,
            operator: PropertyOperator.Exact,
        },
    ])
    return combineUrl(
        urls.activity(ActivityTab.ExploreEvents),
        {},
        { q: { ...query, source: { ...query.source, after } } }
    ).url
}
