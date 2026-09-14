import { combineUrl } from 'kea-router'

import { getDefaultEventsSceneQuery } from 'scenes/activity/explore/defaults'
import { urls } from 'scenes/urls'

import type { EventsQuery } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { ActivityTab, PropertyFilterType } from '~/types'

import { TaxonomicFilterGroupType } from './types'
import type { TaxonomicFilterGroup } from './types'

export interface TaxonomicEmptySearchDestination {
    label: string
    url: string
}

let returnedFromEmptySearchDestination = false

export function markEmptySearchDestinationOpened(onReturn: () => void): void {
    returnedFromEmptySearchDestination = false

    window.addEventListener(
        'focus',
        () => {
            returnedFromEmptySearchDestination = true
            onReturn()
        },
        { once: true }
    )
}

export function consumeEmptySearchDestinationReturn(): boolean {
    const returned = returnedFromEmptySearchDestination
    returnedFromEmptySearchDestination = false
    return returned
}

const PERSON_GROUP_TYPES = new Set<TaxonomicFilterGroupType>([
    TaxonomicFilterGroupType.EmailAddresses,
    TaxonomicFilterGroupType.PersonMetadata,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.Persons,
])

const EVENT_GROUP_TYPES = new Set<TaxonomicFilterGroupType>([
    TaxonomicFilterGroupType.AutocaptureEvents,
    TaxonomicFilterGroupType.CustomEvents,
    TaxonomicFilterGroupType.EventFeatureFlags,
    TaxonomicFilterGroupType.EventMetadata,
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.Events,
    TaxonomicFilterGroupType.InternalEvents,
    TaxonomicFilterGroupType.InternalEventProperties,
    TaxonomicFilterGroupType.MCPProperties,
    TaxonomicFilterGroupType.NumericalEventProperties,
])

export function taxonomicEmptySearchDestination(
    group: TaxonomicFilterGroup | undefined,
    eventNames: string[] = []
): TaxonomicEmptySearchDestination | null {
    if (!group && eventNames.length === 0) {
        return null
    }

    if (group && PERSON_GROUP_TYPES.has(group.type)) {
        return {
            label: 'persons',
            url: urls.persons(),
        }
    }

    if (group?.groupTypeIndex !== undefined) {
        return {
            label: group.name,
            url: urls.groups(group.groupTypeIndex),
        }
    }

    const contextualEventNames = group ? eventNamesForGroup(group.type, eventNames) : eventNames
    if ((group && EVENT_GROUP_TYPES.has(group.type)) || contextualEventNames.length > 0) {
        const defaultQuery = getDefaultEventsSceneQuery()
        const query = {
            ...defaultQuery,
            source: {
                ...defaultQuery.source,
                ...eventNamesFilter(contextualEventNames),
            },
        }
        return {
            label: 'Explore',
            url: combineUrl(urls.activity(ActivityTab.ExploreEvents), {}, { q: query }).url,
        }
    }

    return null
}

function eventNamesForGroup(groupType: TaxonomicFilterGroupType, eventNames: string[]): string[] {
    if (groupType === TaxonomicFilterGroupType.PageviewEvents || groupType === TaxonomicFilterGroupType.PageviewUrls) {
        return ['$pageview']
    }
    if (groupType === TaxonomicFilterGroupType.ScreenEvents || groupType === TaxonomicFilterGroupType.Screens) {
        return ['$screen']
    }
    if (groupType === TaxonomicFilterGroupType.AutocaptureEvents) {
        return ['$autocapture']
    }
    return eventNames
}

function eventNamesFilter(eventNames: string[]): Pick<EventsQuery, 'event' | 'properties'> {
    if (eventNames.length === 0) {
        return {}
    }
    return eventNames.length === 1
        ? { event: eventNames[0] }
        : { properties: [{ type: PropertyFilterType.HogQL, key: hogql`event IN ${eventNames}` }] }
}
