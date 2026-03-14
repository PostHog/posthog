import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { toolbarConfigLogic } from '~/toolbar/core/toolbarConfigLogic'
import { classifyEvent, eventDebugMenuLogic } from '~/toolbar/debug/eventDebugMenuLogic'
import { EventType } from '~/types'

function makeEvent(overrides: Partial<EventType> = {}): EventType {
    return {
        id: '1',
        distinct_id: 'user-1',
        event: 'custom_event',
        timestamp: '2026-03-07T12:00:00.000Z',
        properties: { $browser: 'Chrome' },
        elements: [],
        uuid: `uuid-${Math.random().toString(36).slice(2)}`,
        ...overrides,
    }
}

describe('eventDebugMenuLogic', () => {
    let logic: ReturnType<typeof eventDebugMenuLogic.build>

    beforeEach(() => {
        initKeaTests()
        toolbarConfigLogic
            .build({
                apiURL: 'http://localhost',
                accessToken: 'test-token',
                refreshToken: 'test-refresh',
                clientId: 'test-client',
            })
            .mount()
        logic = eventDebugMenuLogic()
        logic.mount()
    })

    it('has expected defaults', () => {
        expectLogic(logic).toMatchValues({
            events: [],
            searchText: '',
            isPaused: false,
            pinnedEventIds: new Set(),
            selectedEventTypes: ['posthog', 'custom'],
            hidePostHogProperties: false,
            hidePostHogFlags: false,
            relativeTimestamps: false,
        })
    })

    describe('relative timestamps', () => {
        it('toggles relative timestamps', () => {
            expect(logic.values.relativeTimestamps).toBe(false)
            logic.actions.toggleRelativeTimestamps()
            expect(logic.values.relativeTimestamps).toBe(true)
            logic.actions.toggleRelativeTimestamps()
            expect(logic.values.relativeTimestamps).toBe(false)
        })
    })

    describe('classifyEvent', () => {
        it.each([
            ['$pageview', 'posthog'],
            ['$autocapture', 'posthog'],
            ['$snapshot', 'snapshot'],
            ['my_custom_event', 'custom'],
            ['clicked_button', 'custom'],
        ])('classifies "%s" as "%s"', (eventName, expected) => {
            expect(classifyEvent(makeEvent({ event: eventName }))).toBe(expected)
        })
    })

    describe('adding events', () => {
        it('prepends new events to the list', () => {
            const event1 = makeEvent({ event: 'first' })
            const event2 = makeEvent({ event: 'second' })

            logic.actions.addEvent(event1)
            logic.actions.addEvent(event2)

            expect(logic.values.events).toHaveLength(2)
            expect(logic.values.events[0].event).toBe('second')
            expect(logic.values.events[1].event).toBe('first')
        })

        it('assigns a uuid if missing', () => {
            logic.actions.addEvent(makeEvent({ uuid: undefined }))
            expect(logic.values.events[0].uuid).toBeTruthy()
        })
    })

    describe('search filtering', () => {
        beforeEach(() => {
            logic.actions.addEvent(makeEvent({ event: '$pageview' }))
            logic.actions.addEvent(makeEvent({ event: 'button_clicked' }))
            logic.actions.addEvent(makeEvent({ event: '$autocapture' }))
        })

        it('filters by plain text (case-insensitive)', () => {
            logic.actions.setSearchText('button')
            expect(logic.values.searchFilteredEvents).toHaveLength(1)
            expect(logic.values.searchFilteredEvents[0].event).toBe('button_clicked')
        })

        it('filters by regex pattern', () => {
            logic.actions.setSearchText('/^\\$page/')
            expect(logic.values.searchFilteredEvents).toHaveLength(1)
            expect(logic.values.searchFilteredEvents[0].event).toBe('$pageview')
        })

        it('falls back to plain match on invalid regex', () => {
            logic.actions.setSearchText('/[invalid/')
            expect(logic.values.searchFilteredEvents).toHaveLength(0)
        })

        it('shows all events when search is empty', () => {
            logic.actions.setSearchText('')
            expect(logic.values.searchFilteredEvents).toHaveLength(3)
        })
    })

    describe('event type filtering', () => {
        beforeEach(() => {
            logic.actions.addEvent(makeEvent({ event: '$pageview' }))
            logic.actions.addEvent(makeEvent({ event: 'custom_event' }))
            logic.actions.addEvent(makeEvent({ event: '$snapshot' }))
        })

        it('filters by selected event types (default: posthog + custom)', () => {
            expect(logic.values.activeFilteredEvents).toHaveLength(2)
        })

        it('shows snapshot events when enabled', () => {
            logic.actions.setSelectedEventType('snapshot', true)
            expect(logic.values.activeFilteredEvents).toHaveLength(3)
        })

        it('hides custom events when disabled', () => {
            logic.actions.setSelectedEventType('custom', false)
            expect(logic.values.activeFilteredEvents).toHaveLength(1)
            expect(logic.values.activeFilteredEvents[0].event).toBe('$pageview')
        })
    })

    describe('searchFilteredEventsCount', () => {
        beforeEach(() => {
            logic.actions.addEvent(makeEvent({ event: '$pageview' }))
            logic.actions.addEvent(makeEvent({ event: '$autocapture' }))
            logic.actions.addEvent(makeEvent({ event: 'custom_event' }))
            logic.actions.addEvent(makeEvent({ event: '$snapshot' }))
        })

        it('counts events by category', () => {
            expect(logic.values.searchFilteredEventsCount).toEqual({
                posthog: 2,
                custom: 1,
                snapshot: 1,
            })
        })

        it('counts only search-matched events', () => {
            logic.actions.setSearchText('page')
            expect(logic.values.searchFilteredEventsCount).toEqual({
                posthog: 1,
                custom: 0,
                snapshot: 0,
            })
        })
    })

    describe('pinning', () => {
        it('toggles pinned event ids', () => {
            logic.actions.togglePinnedEvent('uuid-1')
            expect(logic.values.pinnedEventIds.has('uuid-1')).toBe(true)

            logic.actions.togglePinnedEvent('uuid-1')
            expect(logic.values.pinnedEventIds.has('uuid-1')).toBe(false)
        })

        it('separates pinned and unpinned events', () => {
            const pinned = makeEvent({ event: 'pinned_event', uuid: 'pin-uuid' })
            const unpinned = makeEvent({ event: 'unpinned_event', uuid: 'unpin-uuid' })

            logic.actions.addEvent(unpinned)
            logic.actions.addEvent(pinned)
            logic.actions.togglePinnedEvent('pin-uuid')

            expect(logic.values.pinnedEvents).toHaveLength(1)
            expect(logic.values.pinnedEvents[0].uuid).toBe('pin-uuid')
            expect(logic.values.unpinnedEvents).toHaveLength(1)
            expect(logic.values.unpinnedEvents[0].uuid).toBe('unpin-uuid')
        })

        it('returns all events as unpinned when nothing is pinned', () => {
            logic.actions.addEvent(makeEvent())
            logic.actions.addEvent(makeEvent())

            expect(logic.values.pinnedEvents).toHaveLength(0)
            expect(logic.values.unpinnedEvents).toHaveLength(2)
        })
    })

    describe('pause/resume', () => {
        it('toggles paused state', () => {
            expect(logic.values.isPaused).toBe(false)
            logic.actions.togglePaused()
            expect(logic.values.isPaused).toBe(true)
            logic.actions.togglePaused()
            expect(logic.values.isPaused).toBe(false)
        })

        it('buffers events while paused and shows pre-pause snapshot', () => {
            logic.actions.addEvent(makeEvent({ event: 'before_pause', uuid: 'before' }))
            logic.actions.togglePaused()

            logic.actions.addEvent(makeEvent({ event: 'during_pause', uuid: 'during' }))

            // visibleEvents should only show the pre-pause event
            expect(logic.values.visibleEvents).toHaveLength(1)
            expect(logic.values.visibleEvents[0].event).toBe('before_pause')
            expect(logic.values.bufferedCount).toBe(1)
        })

        it('shows all events after resume', () => {
            logic.actions.addEvent(makeEvent({ event: 'before_pause' }))
            logic.actions.togglePaused()
            logic.actions.addEvent(makeEvent({ event: 'during_pause' }))
            logic.actions.togglePaused() // resume

            expect(logic.values.visibleEvents).toHaveLength(2)
            expect(logic.values.bufferedCount).toBe(0)
        })
    })

    describe('clear events', () => {
        it('clears all events, buffered events, and pins', () => {
            logic.actions.addEvent(makeEvent({ uuid: 'uuid-1' }))
            logic.actions.addEvent(makeEvent({ uuid: 'uuid-2' }))
            logic.actions.togglePinnedEvent('uuid-1')

            logic.actions.clearEvents()

            expect(logic.values.events).toHaveLength(0)
            expect(logic.values.pinnedEventIds.size).toBe(0)
        })
    })

    describe('totalEventsCount', () => {
        it('reflects visible event count', () => {
            logic.actions.addEvent(makeEvent())
            logic.actions.addEvent(makeEvent())
            logic.actions.addEvent(makeEvent())

            expect(logic.values.totalEventsCount).toBe(3)
        })
    })

    describe('expanded properties', () => {
        it('returns empty when no event is expanded', () => {
            expect(logic.values.expandedProperties).toEqual([])
        })

        it('returns properties for expanded event', () => {
            const event = makeEvent({ uuid: 'expand-me', properties: { key: 'value', $browser: 'Chrome' } })
            logic.actions.addEvent(event)
            logic.actions.markExpanded('expand-me')

            expect(logic.values.expandedProperties).toEqual({ key: 'value', $browser: 'Chrome' })
        })

        it('filters posthog properties when hidePostHogProperties is true', () => {
            const event = makeEvent({
                uuid: 'expand-me',
                properties: { custom_key: 'value', $browser: 'Chrome' },
            })
            logic.actions.addEvent(event)
            logic.actions.markExpanded('expand-me')
            logic.actions.setHidePostHogProperties(true)

            expect(logic.values.expandedProperties).toEqual({ custom_key: 'value' })
        })

        it('filters feature flags when hidePostHogFlags is true', () => {
            const event = makeEvent({
                uuid: 'expand-me',
                properties: {
                    custom_key: 'value',
                    $active_feature_flags: ['flag-1'],
                    '$feature/my-flag': true,
                },
            })
            logic.actions.addEvent(event)
            logic.actions.markExpanded('expand-me')
            logic.actions.setHidePostHogFlags(true)

            expect(logic.values.expandedProperties).toEqual({ custom_key: 'value' })
        })
    })

    describe('exportableEvents', () => {
        it('maps active filtered events to export format', () => {
            const event = makeEvent({
                uuid: 'export-uuid',
                event: 'test_event',
                timestamp: '2026-03-07T12:00:00.000Z',
                properties: { key: 'value' },
            })
            logic.actions.addEvent(event)

            expect(logic.values.exportableEvents).toEqual([
                {
                    event: 'test_event',
                    timestamp: '2026-03-07T12:00:00.000Z',
                    properties: { key: 'value' },
                    uuid: 'export-uuid',
                },
            ])
        })
    })
})
