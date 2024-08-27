import { filterInspectorListItems } from 'scenes/session-recordings/player/inspector/inspectorListFiltering'
import {
    InspectorListBrowserVisibility,
    InspectorListItemDoctor,
    InspectorListItemEvent,
    InspectorListOfflineStatusChange,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { SharedListMiniFilter } from 'scenes/session-recordings/player/playerSettingsLogic'

import { PerformanceEvent, SessionRecordingPlayerTab } from '~/types'

describe('filtering inspector list items', () => {
    describe('the all tab', () => {
        it('includes browser visibility', () => {
            expect(
                filterInspectorListItems({
                    allItems: [
                        {
                            type: 'browser-visibility',
                        } as InspectorListBrowserVisibility,
                    ],
                    tab: SessionRecordingPlayerTab.ALL,
                    miniFiltersByKey: { 'all-everything': { enabled: true } as unknown as SharedListMiniFilter },
                    showOnlyMatching: false,
                    showMatchingEventsFilter: false,
                    windowIdFilter: null,
                })
            ).toHaveLength(1)
        })

        it('hides doctor items in everything mode', () => {
            const filteredItems = filterInspectorListItems({
                allItems: [
                    {
                        type: 'browser-visibility',
                    } as InspectorListBrowserVisibility,
                    {
                        type: 'doctor',
                    } as InspectorListItemDoctor,
                ],
                tab: SessionRecordingPlayerTab.ALL,
                miniFiltersByKey: { 'all-everything': { enabled: true } as unknown as SharedListMiniFilter },
                showOnlyMatching: false,
                showMatchingEventsFilter: false,
                windowIdFilter: null,
            })
            expect(filteredItems.map((item) => item.type)).toEqual(['browser-visibility'])
        })
    })

    describe('the events tab', () => {
        it('filters by window id', () => {
            expect(
                filterInspectorListItems({
                    allItems: [
                        {
                            type: SessionRecordingPlayerTab.EVENTS,
                            windowId: 'this window',
                            data: { event: '$exception' } as unknown as PerformanceEvent,
                        } as unknown as InspectorListItemEvent,
                        {
                            type: SessionRecordingPlayerTab.EVENTS,
                            windowId: 'a different window',
                            data: { event: '$exception' } as unknown as PerformanceEvent,
                        } as unknown as InspectorListItemEvent,
                    ],
                    tab: SessionRecordingPlayerTab.EVENTS,
                    miniFiltersByKey: { 'events-all': { enabled: true } as unknown as SharedListMiniFilter },
                    showOnlyMatching: false,
                    showMatchingEventsFilter: false,
                    windowIdFilter: 'a different window',
                })
            ).toHaveLength(1)
        })

        it('excludes browser visibility on console filter', () => {
            expect(
                filterInspectorListItems({
                    allItems: [
                        {
                            type: 'browser-visibility',
                        } as InspectorListBrowserVisibility,
                    ],
                    tab: SessionRecordingPlayerTab.EVENTS,
                    miniFiltersByKey: { 'all-everything': { enabled: false } as unknown as SharedListMiniFilter },
                    showOnlyMatching: false,
                    showMatchingEventsFilter: false,
                    windowIdFilter: null,
                })
            ).toHaveLength(0)
        })

        it('excludes browser visibility when show only matching', () => {
            expect(
                filterInspectorListItems({
                    allItems: [
                        {
                            type: 'browser-visibility',
                        } as InspectorListBrowserVisibility,
                    ],
                    tab: SessionRecordingPlayerTab.EVENTS,
                    miniFiltersByKey: { 'all-everything': { enabled: true } as unknown as SharedListMiniFilter },
                    showOnlyMatching: true,
                    showMatchingEventsFilter: true,
                    windowIdFilter: null,
                })
            ).toHaveLength(0)
        })
    })

    describe('the doctor tab', () => {
        it('ignores events that are not exceptions', () => {
            expect(
                filterInspectorListItems({
                    allItems: [
                        {
                            type: SessionRecordingPlayerTab.EVENTS,
                            data: { event: 'an event' } as unknown as PerformanceEvent,
                        } as unknown as InspectorListItemEvent,
                    ],
                    tab: SessionRecordingPlayerTab.DOCTOR,
                    miniFiltersByKey: {},
                    showOnlyMatching: false,
                    showMatchingEventsFilter: false,
                    windowIdFilter: null,
                })
            ).toHaveLength(0)
        })

        it('includes events that are exceptions', () => {
            expect(
                filterInspectorListItems({
                    allItems: [
                        {
                            type: SessionRecordingPlayerTab.EVENTS,
                            data: { event: '$exception' } as unknown as PerformanceEvent,
                        } as unknown as InspectorListItemEvent,
                    ],
                    tab: SessionRecordingPlayerTab.DOCTOR,
                    miniFiltersByKey: {},
                    showOnlyMatching: false,
                    showMatchingEventsFilter: false,
                    windowIdFilter: null,
                })
            ).toHaveLength(1)
        })

        it('includes browser offline status', () => {
            expect(
                filterInspectorListItems({
                    allItems: [
                        {
                            type: 'offline-status',
                        } as unknown as InspectorListOfflineStatusChange,
                    ],
                    tab: SessionRecordingPlayerTab.DOCTOR,
                    miniFiltersByKey: {},
                    showOnlyMatching: false,
                    showMatchingEventsFilter: false,
                    windowIdFilter: null,
                })
            ).toHaveLength(1)
        })

        it('includes browser visibility status', () => {
            expect(
                filterInspectorListItems({
                    allItems: [
                        {
                            type: 'browser-visibility',
                        } as InspectorListBrowserVisibility,
                    ],
                    tab: SessionRecordingPlayerTab.DOCTOR,
                    miniFiltersByKey: {},
                    showOnlyMatching: false,
                    showMatchingEventsFilter: false,
                    windowIdFilter: null,
                })
            ).toHaveLength(1)
        })
    })
})
