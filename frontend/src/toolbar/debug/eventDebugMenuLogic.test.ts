import { expectLogic } from 'kea-test-utils'

import { RegexMatchingResult, startRegexMatching } from 'lib/regex/regexMatching'

import { initKeaTests } from '~/test/init'
import { classifyEvent, eventDebugMenuLogic } from '~/toolbar/debug/eventDebugMenuLogic'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { EventType } from '~/types'

jest.mock('lib/regex/regexMatching', () => ({ startRegexMatching: jest.fn() }))

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
        jest.mocked(startRegexMatching)
            .mockReset()
            .mockImplementation((checks) => ({
                promise: Promise.resolve({
                    status: 'success',
                    results: checks.map(({ pattern, flags, subject }) => {
                        try {
                            return { matches: new RegExp(pattern, flags).test(subject) }
                        } catch {
                            return { error: 'syntax_error' as const }
                        }
                    }),
                }),
                cancel: jest.fn(),
            }))
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

        it('filters by regex pattern', async () => {
            logic.actions.setSearchText('/^\\$page/')
            expect(logic.values.searchPending).toBe(true)
            await Promise.resolve()
            expect(logic.values.searchFilteredEvents).toHaveLength(1)
            expect(logic.values.searchFilteredEvents[0].event).toBe('$pageview')
        })

        it('falls back to plain match on invalid regex', async () => {
            logic.actions.addEvent(makeEvent({ event: '/[invalid/' }))
            logic.actions.setSearchText('/[invalid/')
            await Promise.resolve()
            expect(logic.values.searchFilteredEvents.map((event) => event.event)).toEqual(['/[invalid/'])
            expect(logic.values.searchError).toBeNull()
        })

        it('shows all events when search is empty', () => {
            logic.actions.setSearchText('')
            expect(logic.values.searchFilteredEvents).toHaveLength(3)
        })
    })

    it('coalesces streaming work, publishes completed batches, and latches failures until the query changes', async () => {
        const pending: { resolve: (result: RegexMatchingResult) => void; cancel: jest.Mock }[] = []
        jest.mocked(startRegexMatching).mockImplementation(() => {
            let resolve!: (result: RegexMatchingResult) => void
            const promise = new Promise<RegexMatchingResult>((done) => {
                resolve = done
            })
            const request = { resolve, cancel: jest.fn() }
            pending.push(request)
            return { promise, cancel: request.cancel }
        })
        logic.actions.addEvent(makeEvent({ event: 'match', uuid: 'first' }))
        logic.actions.setSearchText('/match/')
        for (let i = 0; i < 20; i++) {
            logic.actions.addEvent(makeEvent({ event: 'match' }))
        }
        expect(pending).toHaveLength(1)
        expect(pending[0].cancel).not.toHaveBeenCalled()
        pending[0].resolve({ status: 'success', results: [{ matches: true }] })
        await Promise.resolve()
        expect(logic.values.searchFilteredEvents.map((event) => event.uuid)).toEqual(['first'])
        expect(pending).toHaveLength(2)
        pending[1].resolve({ status: 'error', error: 'timeout' })
        await Promise.resolve()
        expect(logic.values.searchPending).toBe(false)
        expect(logic.values.searchError).toBe('timeout')
        for (let i = 0; i < 20; i++) {
            logic.actions.addEvent(makeEvent())
        }
        expect(pending).toHaveLength(2)
        logic.actions.setSearchText('MATCH')
        expect(logic.values.searchError).toBeNull()
        expect(logic.values.searchFilteredEvents).toHaveLength(21)
        expect(pending).toHaveLength(2)
    })

    it.each([
        ['/a/g', ['a', 'a', 'ba'], 3],
        ['/a/y', ['a', 'a', 'ba'], 2],
        ['/(?<=foo)(bar)\\1/i', ['FOOBARBAR', 'bar'], 1],
        ['/^a.b$/s', ['a\nb', 'ab'], 1],
        ['/^b/m', ['a\nb', 'ab'], 1],
        ['/a/ii', ['/a/ii', 'a'], 1],
        ['/a/d', ['/a/d', 'a'], 1],
        ['//', ['//', 'a'], 1],
    ])('preserves search syntax and per-event flags for %s', async (query, names, count) => {
        for (const event of names) {
            logic.actions.addEvent(makeEvent({ event }))
        }
        logic.actions.setSearchText(query)
        await Promise.resolve()
        expect(logic.values.searchFilteredEvents).toHaveLength(count)
    })

    it.each(['timeout', 'startup_timeout', 'unavailable', 'worker_error', 'hidden'] as const)(
        'latches %s across stream, pause, clear and identical query actions',
        async (error) => {
            jest.mocked(startRegexMatching).mockReturnValue({
                promise: Promise.resolve({ status: 'error', error }),
                cancel: jest.fn(),
            })
            logic.actions.addEvent(makeEvent())
            logic.actions.setSearchText('/custom/')
            await Promise.resolve()
            logic.actions.setSearchText('/custom/')
            logic.actions.togglePaused()
            logic.actions.clearEvents()
            logic.actions.addEvent(makeEvent())
            logic.actions.togglePaused()
            expect(startRegexMatching).toHaveBeenCalledTimes(1)
            expect(logic.values.searchError).toBe(error)
            expect(logic.values.searchPending).toBe(false)
            logic.actions.setSearchText('CUSTOM')
            expect(logic.values.searchFilteredEvents).toHaveLength(1)
            expect(logic.values.searchError).toBeNull()
            expect(startRegexMatching).toHaveBeenCalledTimes(1)
        }
    )

    it('cancels replaced queries and clear, ignores stale results, and disposes active work', async () => {
        const pending: { resolve: (result: RegexMatchingResult) => void; cancel: jest.Mock }[] = []
        jest.mocked(startRegexMatching).mockImplementation(() => {
            let resolve!: (result: RegexMatchingResult) => void
            const promise = new Promise<RegexMatchingResult>((done) => {
                resolve = done
            })
            const request = { resolve, cancel: jest.fn() }
            pending.push(request)
            return { promise, cancel: request.cancel }
        })
        logic.actions.addEvent(makeEvent({ event: 'first' }))
        logic.actions.setSearchText('/first/')
        logic.actions.setSearchText('/second/')
        expect(pending[0].cancel).toHaveBeenCalledTimes(1)
        pending[0].resolve({ status: 'success', results: [{ matches: true }] })
        await Promise.resolve()
        expect(logic.values.searchFilteredEvents).toEqual([])
        expect(logic.values.searchPending).toBe(true)
        logic.actions.clearEvents()
        expect(pending[1].cancel).toHaveBeenCalledTimes(1)
        pending[1].resolve({ status: 'success', results: [{ matches: true }] })
        await Promise.resolve()
        expect(logic.values.searchPending).toBe(false)
        logic.actions.addEvent(makeEvent({ event: 'second' }))
        logic.unmount()
        logic.unmount()
        expect(pending[2].cancel).toHaveBeenCalledTimes(1)
        pending[2].resolve({ status: 'success', results: [{ matches: true }] })
        await Promise.resolve()
    })

    it('keeps regex categories, pins and export aligned while pausing and resuming', async () => {
        logic.actions.addEvent(makeEvent({ event: '$pageview', uuid: 'pinned' }))
        logic.actions.togglePinnedEvent('pinned')
        logic.actions.setSearchText('/page|snapshot/')
        await Promise.resolve()
        logic.actions.togglePaused()
        logic.actions.addEvent(makeEvent({ event: '$snapshot', uuid: 'buffered' }))
        await Promise.resolve()
        expect(logic.values.searchFilteredEventsCount).toEqual({ posthog: 1, custom: 0, snapshot: 0 })
        expect(logic.values.pinnedEvents.map((event) => event.uuid)).toEqual(['pinned'])
        logic.actions.togglePaused()
        await Promise.resolve()
        logic.actions.setSelectedEventType('snapshot', true)
        expect(logic.values.searchFilteredEventsCount).toEqual({ posthog: 1, custom: 0, snapshot: 1 })
        expect(logic.values.exportableEvents).toHaveLength(2)
        expect(logic.values.unpinnedEvents.map((event) => event.uuid)).toEqual(['buffered'])
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
