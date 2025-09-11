import { InspectorListItemPerformance } from 'scenes/session-recordings/apm/performanceEventDataLogic'
import { filterInspectorListItems } from 'scenes/session-recordings/player/inspector/inspectorListFiltering'
import { SharedListMiniFilter } from 'scenes/session-recordings/player/inspector/miniFiltersLogic'
import {
    InspectorListBrowserVisibility,
    InspectorListItemComment,
    InspectorListItemDoctor,
    InspectorListItemEvent,
    InspectorListItemNotebookComment,
    InspectorListOfflineStatusChange,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

import { PerformanceEvent } from '~/types'

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
                hasEventsToDisplay: false,
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
                hasEventsToDisplay: true,
            }).map((item) => item.type)
        ).toEqual(['browser-visibility', 'offline-status', 'events'])
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
            hasEventsToDisplay: true,
        })
        expect(filteredItems).toHaveLength(expectedLength)
    })

    it.each([
        [true, 2],
        [false, 0],
    ])('hides/shows comment items when %s', (enabled, expectedLength) => {
        const filteredItems = filterInspectorListItems({
            allItems: [
                {
                    type: 'doctor',
                } as InspectorListItemDoctor,
                {
                    type: 'comment',
                    source: 'notebook',
                } as InspectorListItemNotebookComment,
                {
                    type: 'comment',
                    source: 'comment',
                } as InspectorListItemComment,
            ],
            miniFiltersByKey: { comment: { enabled } as unknown as SharedListMiniFilter },
            showOnlyMatching: false,
            allowMatchingEventsFilter: false,
            trackedWindow: null,
            hasEventsToDisplay: true,
        })
        expect(filteredItems).toHaveLength(expectedLength)
    })

    it('filters by window id', () => {
        expect(
            filterInspectorListItems({
                allItems: [
                    {
                        type: 'events',
                        windowId: 'this window',
                        data: { event: '$exception' } as unknown as PerformanceEvent,
                    } as unknown as InspectorListItemEvent,
                    {
                        type: 'events',
                        windowId: 'a different window',
                        data: { event: '$exception' } as unknown as PerformanceEvent,
                    } as unknown as InspectorListItemEvent,
                ],
                miniFiltersByKey: { 'events-exceptions': { enabled: true } as unknown as SharedListMiniFilter },
                showOnlyMatching: false,
                allowMatchingEventsFilter: false,
                trackedWindow: 'a different window',
                hasEventsToDisplay: true,
            })
        ).toHaveLength(1)
    })

    it('empty mini filters hides everything', () => {
        expect(
            filterInspectorListItems({
                allItems: [
                    {
                        type: 'events',
                        data: { event: 'an event' } as unknown as PerformanceEvent,
                    } as unknown as InspectorListItemEvent,
                ],
                miniFiltersByKey: {},
                showOnlyMatching: false,
                allowMatchingEventsFilter: false,
                trackedWindow: null,
                hasEventsToDisplay: true,
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
                        type: 'events',
                        data: { event: '$exception' } as unknown as PerformanceEvent,
                    } as unknown as InspectorListItemEvent,
                ],
                miniFiltersByKey: { 'events-exceptions': { enabled } as unknown as SharedListMiniFilter },
                showOnlyMatching: false,
                allowMatchingEventsFilter: false,
                trackedWindow: null,
                hasEventsToDisplay: true,
            })
        ).toHaveLength(expectedLength)
    })

    it('only shows matching events when show matching events is true', () => {
        expect(
            filterInspectorListItems({
                allItems: [
                    {
                        type: 'events',
                        data: { event: '$exception' } as unknown as PerformanceEvent,
                        highlightColor: 'primary',
                    } as unknown as InspectorListItemEvent,
                    {
                        type: 'network',
                        data: { event: '$pageview' } as unknown as PerformanceEvent,
                    } as unknown as InspectorListItemPerformance,
                    {
                        type: 'doctor',
                        data: { event: '$pageview' } as unknown as PerformanceEvent,
                    } as unknown as InspectorListItemDoctor,
                ],
                miniFiltersByKey: { 'events-exceptions': { enabled: true } as unknown as SharedListMiniFilter },
                showOnlyMatching: true,
                allowMatchingEventsFilter: true,
                trackedWindow: null,
                hasEventsToDisplay: true,
            })
        ).toHaveLength(1)
    })
})
