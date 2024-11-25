import { filterInspectorListItems } from 'scenes/session-recordings/player/inspector/inspectorListFiltering'
import { SharedListMiniFilter } from 'scenes/session-recordings/player/inspector/miniFiltersLogic'
import {
    InspectorListBrowserVisibility,
    InspectorListItemComment,
    InspectorListItemDoctor,
    InspectorListItemEvent,
    InspectorListOfflineStatusChange,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

import { FilterableInspectorListItemTypes, PerformanceEvent } from '~/types'

describe('filtering inspector list items', () => {
    it('hides context events when no other events', () => {
        expect(
            filterInspectorListItems({
                allItems: [
                    {
                        type: 'browser-visibility',
                    } as InspectorListBrowserVisibility,
                    {
                        type: 'offline-status',
                    } as unknown as InspectorListOfflineStatusChange,
                    {
                        type: 'comment',
                    } as unknown as InspectorListItemComment,
                ],
                miniFiltersByKey: { 'events-posthog': { enabled: false } as unknown as SharedListMiniFilter },
                showOnlyMatching: false,
                allowMatchingEventsFilter: false,
                trackedWindow: null,
            })
        ).toHaveLength(0)
    })

    it('shows context events when other events', () => {
        expect(
            filterInspectorListItems({
                allItems: [
                    {
                        type: 'browser-visibility',
                    } as InspectorListBrowserVisibility,
                    {
                        type: 'offline-status',
                    } as unknown as InspectorListOfflineStatusChange,
                    {
                        type: 'comment',
                    } as unknown as InspectorListItemComment,
                    {
                        data: { event: '$pageview' },
                        type: 'events',
                    } as InspectorListItemEvent,
                ],
                miniFiltersByKey: { 'events-pageview': { enabled: true } as unknown as SharedListMiniFilter },
                showOnlyMatching: false,
                allowMatchingEventsFilter: false,
                trackedWindow: null,
            }).map((item) => item.type)
        ).toEqual(['browser-visibility', 'offline-status', 'comment', 'events'])
    })

    it.each([
        [true, 1],
        [false, 0],
    ])('hides/shows doctor items when %s', (enabled, expectedLength) => {
        const filteredItems = filterInspectorListItems({
            allItems: [
                {
                    type: 'doctor',
                } as InspectorListItemDoctor,
            ],
            miniFiltersByKey: { doctor: { enabled } as unknown as SharedListMiniFilter },
            showOnlyMatching: false,
            allowMatchingEventsFilter: false,
            trackedWindow: null,
        })
        expect(filteredItems).toHaveLength(expectedLength)
    })

    it('filters by window id', () => {
        expect(
            filterInspectorListItems({
                allItems: [
                    {
                        type: FilterableInspectorListItemTypes.EVENTS,
                        windowId: 'this window',
                        data: { event: '$exception' } as unknown as PerformanceEvent,
                    } as unknown as InspectorListItemEvent,
                    {
                        type: FilterableInspectorListItemTypes.EVENTS,
                        windowId: 'a different window',
                        data: { event: '$exception' } as unknown as PerformanceEvent,
                    } as unknown as InspectorListItemEvent,
                ],
                miniFiltersByKey: { 'events-exceptions': { enabled: true } as unknown as SharedListMiniFilter },
                showOnlyMatching: false,
                allowMatchingEventsFilter: false,
                trackedWindow: 'a different window',
            })
        ).toHaveLength(1)
    })

    it('empty mini filters hides everything', () => {
        expect(
            filterInspectorListItems({
                allItems: [
                    {
                        type: FilterableInspectorListItemTypes.EVENTS,
                        data: { event: 'an event' } as unknown as PerformanceEvent,
                    } as unknown as InspectorListItemEvent,
                ],
                miniFiltersByKey: {},
                showOnlyMatching: false,
                allowMatchingEventsFilter: false,
                trackedWindow: null,
            })
        ).toHaveLength(0)
    })

    it.each([
        [true, 1],
        [false, 0],
    ])('hides/shows exceptions when %s', (enabled, expectedLength) => {
        expect(
            filterInspectorListItems({
                allItems: [
                    {
                        type: FilterableInspectorListItemTypes.EVENTS,
                        data: { event: '$exception' } as unknown as PerformanceEvent,
                    } as unknown as InspectorListItemEvent,
                ],
                miniFiltersByKey: { 'events-exceptions': { enabled } as unknown as SharedListMiniFilter },
                showOnlyMatching: false,
                allowMatchingEventsFilter: false,
                trackedWindow: null,
            })
        ).toHaveLength(expectedLength)
    })
})
