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
    destination: 'explore' | 'persons' | 'groups'
    url: string
}

/** Matches the recovery funnel window. A later selection has no link to the click, so it must not claim the return. */
export const EMPTY_SEARCH_RETURN_WINDOW_MS = 15 * 60 * 1000

let returnedAt: number | null = null
let pendingReturnListener: (() => void) | null = null

export function markEmptySearchDestinationOpened(onReturn: () => void): void {
    returnedAt = null

    if (pendingReturnListener) {
        window.removeEventListener('focus', pendingReturnListener)
    }

    const listener = (): void => {
        returnedAt = Date.now()
        pendingReturnListener = null
        onReturn()
    }
    pendingReturnListener = listener

    window.addEventListener('focus', listener, { once: true })
}

export function consumeEmptySearchDestinationReturn(): boolean {
    const returned = returnedAt !== null && Date.now() - returnedAt < EMPTY_SEARCH_RETURN_WINDOW_MS
    returnedAt = null
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
            destination: 'persons',
            url: urls.persons(),
        }
    }

    if (group?.groupTypeIndex !== undefined) {
        return {
            label: group.name,
            destination: 'groups',
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
                after: '-7d',
                ...eventNamesFilter(contextualEventNames),
            },
        }
        return {
            label: 'Explore',
            destination: 'explore',
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
