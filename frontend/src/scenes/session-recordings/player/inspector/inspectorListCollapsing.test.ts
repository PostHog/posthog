import {
    InspectorListItemConsole,
    InspectorListItemEvent,
    InspectorListItemInactivity,
    collapseAdjacentItems,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

function makeEvent(overrides: Partial<InspectorListItemEvent> = {}): InspectorListItemEvent {
    return {
        type: 'events',
        timestamp: {} as any,
        timeInRecording: 1000,
        search: 'Pageview /',
        key: `event-${Math.random()}`,
        data: { event: '$pageview' } as any,
        ...overrides,
    }
}

function makeConsoleLog(overrides: Partial<InspectorListItemConsole> = {}): InspectorListItemConsole {
    return {
        type: 'console',
        timestamp: {} as any,
        timeInRecording: 1000,
        search: 'retry failed',
        key: `console-${Math.random()}`,
        data: { content: 'retry failed', level: 'warn', timestamp: 1000, windowId: undefined } as any,
        ...overrides,
    }
}

function makeInactivity(durationMs: number): InspectorListItemInactivity {
    return {
        type: 'inactivity',
        timestamp: {} as any,
        timeInRecording: 1000,
        search: '',
        key: `inactivity-${Math.random()}`,
        durationMs,
    }
}

describe('collapseAdjacentItems', () => {
    it('empty in, empty out', () => {
        expect(collapseAdjacentItems([])).toEqual([])
    })

    it('leaves a single event alone', () => {
        const result = collapseAdjacentItems([makeEvent()])
        expect(result).toHaveLength(1)
        expect((result[0] as InspectorListItemEvent).groupedEvents).toBeUndefined()
    })

    it.each([2, 3, 5])('collapses %i identical events into one group', (n) => {
        const result = collapseAdjacentItems(Array.from({ length: n }, () => makeEvent()))
        expect(result).toHaveLength(1)
        expect((result[0] as InspectorListItemEvent).groupedEvents).toHaveLength(n)
    })

    it('breaks the run when the event name changes', () => {
        const items = [
            makeEvent({ data: { event: '$pageview' } as any, search: 'Pageview /' }),
            makeEvent({ data: { event: '$pageleave' } as any, search: 'Pageleave /' }),
            makeEvent({ data: { event: '$pageview' } as any, search: 'Pageview /' }),
        ]
        expect(collapseAdjacentItems(items)).toHaveLength(3)
    })

    it('treats same event name but different search text as distinct', () => {
        const items = [
            makeEvent({ search: 'Clicked button A' }),
            makeEvent({ search: 'Clicked button A' }),
            makeEvent({ search: 'Clicked button B' }),
            makeEvent({ search: 'Clicked button A' }),
        ]
        // A,A group into 1 + B alone + A alone = 3
        const result = collapseAdjacentItems(items)
        expect(result).toHaveLength(3)
        expect((result[0] as InspectorListItemEvent).groupedEvents).toHaveLength(2)
    })

    it('never groups highlighted events', () => {
        const items = Array.from({ length: 4 }, () => makeEvent({ highlightColor: 'primary' }))
        expect(collapseAdjacentItems(items)).toHaveLength(4)
    })

    it('skips a highlighted item then groups the rest', () => {
        const items = [makeEvent({ highlightColor: 'danger' }), makeEvent(), makeEvent(), makeEvent()]
        const result = collapseAdjacentItems(items)
        expect(result).toHaveLength(2)
        expect((result[0] as InspectorListItemEvent).highlightColor).toBe('danger')
        expect((result[1] as InspectorListItemEvent).groupedEvents).toHaveLength(3)
    })

    it('creates separate groups for different event types', () => {
        const pageviews = Array.from({ length: 3 }, () =>
            makeEvent({ data: { event: '$pageview' } as any, search: 'Pageview /' })
        )
        const clicks = Array.from({ length: 2 }, () =>
            makeEvent({ data: { event: '$autocapture' } as any, search: 'Clicked button' })
        )
        const result = collapseAdjacentItems([...pageviews, ...clicks])
        expect(result).toHaveLength(2)
        expect((result[0] as InspectorListItemEvent).groupedEvents).toHaveLength(3)
        expect((result[1] as InspectorListItemEvent).groupedEvents).toHaveLength(2)
    })

    it('sums durations when merging adjacent inactivity items', () => {
        const result = collapseAdjacentItems([makeInactivity(1000), makeInactivity(2000), makeInactivity(500)])
        expect(result).toHaveLength(1)
        expect((result[0] as InspectorListItemInactivity).durationMs).toBe(3500)
    })

    it('an inactivity item in between breaks the event run', () => {
        const items = [makeEvent(), makeEvent(), makeInactivity(1000), makeEvent(), makeEvent()]
        const result = collapseAdjacentItems(items)
        // 2 events grouped + 1 inactivity + 2 events grouped = 3 items
        expect(result).toHaveLength(3)
    })

    it('keeps individual timestamps inside groupedEvents', () => {
        const events = Array.from({ length: 4 }, (_, i) => makeEvent({ timeInRecording: i * 1000, key: `event-${i}` }))
        const result = collapseAdjacentItems(events)
        const grouped = (result[0] as InspectorListItemEvent).groupedEvents!
        expect(grouped.map((e) => e.timeInRecording)).toEqual([0, 1000, 2000, 3000])
    })

    it('does not mutate input items', () => {
        const events = [makeEvent(), makeEvent(), makeEvent()]
        const originals = events.map((e) => ({ ...e }))
        collapseAdjacentItems(events)
        events.forEach((e, i) => {
            expect(e.timeInRecording).toBe(originals[i].timeInRecording)
            expect((e as InspectorListItemEvent).groupedEvents).toBeUndefined()
        })

        const inactivities = [makeInactivity(1000), makeInactivity(2000)]
        const origDurations = inactivities.map((i) => i.durationMs)
        collapseAdjacentItems(inactivities)
        inactivities.forEach((item, i) => {
            expect(item.durationMs).toBe(origDurations[i])
        })
    })

    it('still collapses inactivity when groupEvents is false', () => {
        const items = [makeInactivity(1000), makeInactivity(2000), makeEvent(), makeEvent()]
        const result = collapseAdjacentItems(items, false)
        // inactivity merged into 1, but the 2 events stay separate
        expect(result).toHaveLength(3)
        expect((result[0] as InspectorListItemInactivity).durationMs).toBe(3000)
        expect((result[1] as InspectorListItemEvent).groupedEvents).toBeUndefined()
        expect((result[2] as InspectorListItemEvent).groupedEvents).toBeUndefined()
    })

    it('skips event grouping when groupSimilar is false', () => {
        const items = Array.from({ length: 5 }, () => makeEvent())
        const result = collapseAdjacentItems(items, false)
        expect(result).toHaveLength(5)
        result.forEach((item) => {
            expect((item as InspectorListItemEvent).groupedEvents).toBeUndefined()
        })
    })

    // Console log grouping
    it('leaves a single console log alone', () => {
        const result = collapseAdjacentItems([makeConsoleLog()])
        expect(result).toHaveLength(1)
        expect((result[0] as InspectorListItemConsole).groupedConsoleLogs).toBeUndefined()
    })

    it.each([2, 3, 5])('collapses %i identical console logs into one group', (n) => {
        const result = collapseAdjacentItems(Array.from({ length: n }, () => makeConsoleLog()))
        expect(result).toHaveLength(1)
        expect((result[0] as InspectorListItemConsole).groupedConsoleLogs).toHaveLength(n)
    })

    it('breaks the console log run when content changes', () => {
        const items = [
            makeConsoleLog({ data: { content: 'foo' } as any, search: 'foo' }),
            makeConsoleLog({ data: { content: 'bar' } as any, search: 'bar' }),
            makeConsoleLog({ data: { content: 'foo' } as any, search: 'foo' }),
        ]
        expect(collapseAdjacentItems(items)).toHaveLength(3)
    })

    it('groups console logs with the same highlight color', () => {
        const items = Array.from({ length: 4 }, () => makeConsoleLog({ highlightColor: 'danger' }))
        const result = collapseAdjacentItems(items)
        expect(result).toHaveLength(1)
        expect((result[0] as InspectorListItemConsole).groupedConsoleLogs).toHaveLength(4)
    })

    it('breaks the console log run when highlight color differs', () => {
        const items = [
            makeConsoleLog({ highlightColor: 'danger' }),
            makeConsoleLog({ highlightColor: 'danger' }),
            makeConsoleLog({ highlightColor: 'warning' }),
            makeConsoleLog({ highlightColor: 'danger' }),
        ]
        const result = collapseAdjacentItems(items)
        expect(result).toHaveLength(3)
        expect((result[0] as InspectorListItemConsole).groupedConsoleLogs).toHaveLength(2)
    })

    it('an event in between breaks the console log run', () => {
        const items = [makeConsoleLog(), makeConsoleLog(), makeEvent(), makeConsoleLog(), makeConsoleLog()]
        const result = collapseAdjacentItems(items)
        // 2 logs grouped + 1 event + 2 logs grouped = 3 items
        expect(result).toHaveLength(3)
    })

    it('skips console log grouping when groupSimilar is false', () => {
        const items = Array.from({ length: 5 }, () => makeConsoleLog())
        const result = collapseAdjacentItems(items, false)
        expect(result).toHaveLength(5)
        result.forEach((item) => {
            expect((item as InspectorListItemConsole).groupedConsoleLogs).toBeUndefined()
        })
    })

    it('keeps individual timestamps inside groupedConsoleLogs', () => {
        const logs = Array.from({ length: 4 }, (_, i) =>
            makeConsoleLog({ timeInRecording: i * 1000, key: `console-${i}` })
        )
        const result = collapseAdjacentItems(logs)
        const grouped = (result[0] as InspectorListItemConsole).groupedConsoleLogs!
        expect(grouped.map((e) => e.timeInRecording)).toEqual([0, 1000, 2000, 3000])
    })
})
