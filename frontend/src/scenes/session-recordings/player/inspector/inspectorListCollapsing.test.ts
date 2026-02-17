import {
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

    it('keeps 3 or fewer identical events ungrouped', () => {
        const result = collapseAdjacentItems([makeEvent(), makeEvent(), makeEvent()])
        expect(result).toHaveLength(3)
        result.forEach((item) => {
            expect((item as InspectorListItemEvent).groupedEvents).toBeUndefined()
        })
    })

    it('collapses 4 identical events into one group', () => {
        const result = collapseAdjacentItems([makeEvent(), makeEvent(), makeEvent(), makeEvent()])
        expect(result).toHaveLength(1)
        expect((result[0] as InspectorListItemEvent).groupedEvents).toHaveLength(4)
    })

    it('collapses 5 identical events into one group', () => {
        const result = collapseAdjacentItems(Array.from({ length: 5 }, () => makeEvent()))
        expect(result).toHaveLength(1)
        expect((result[0] as InspectorListItemEvent).groupedEvents).toHaveLength(5)
    })

    it('breaks the run when the event name changes', () => {
        const items = [
            makeEvent({ data: { event: '$pageview' } as any, search: 'Pageview /' }),
            makeEvent({ data: { event: '$pageview' } as any, search: 'Pageview /' }),
            makeEvent({ data: { event: '$pageleave' } as any, search: 'Pageleave /' }),
            makeEvent({ data: { event: '$pageview' } as any, search: 'Pageview /' }),
        ]
        expect(collapseAdjacentItems(items)).toHaveLength(4)
    })

    it('treats same event name but different search text as distinct', () => {
        const items = [
            makeEvent({ search: 'Clicked button A' }),
            makeEvent({ search: 'Clicked button A' }),
            makeEvent({ search: 'Clicked button B' }),
            makeEvent({ search: 'Clicked button A' }),
        ]
        expect(collapseAdjacentItems(items)).toHaveLength(4)
    })

    it('never groups highlighted events', () => {
        const items = Array.from({ length: 4 }, () => makeEvent({ highlightColor: 'primary' }))
        expect(collapseAdjacentItems(items)).toHaveLength(4)
    })

    it('skips a highlighted item then groups the rest', () => {
        const items = [makeEvent({ highlightColor: 'danger' }), makeEvent(), makeEvent(), makeEvent(), makeEvent()]
        const result = collapseAdjacentItems(items)
        expect(result).toHaveLength(2)
        expect((result[0] as InspectorListItemEvent).highlightColor).toBe('danger')
        expect((result[1] as InspectorListItemEvent).groupedEvents).toHaveLength(4)
    })

    it('creates separate groups for different event types', () => {
        const pageviews = Array.from({ length: 4 }, () =>
            makeEvent({ data: { event: '$pageview' } as any, search: 'Pageview /' })
        )
        const clicks = Array.from({ length: 5 }, () =>
            makeEvent({ data: { event: '$autocapture' } as any, search: 'Clicked button' })
        )
        const result = collapseAdjacentItems([...pageviews, ...clicks])
        expect(result).toHaveLength(2)
        expect((result[0] as InspectorListItemEvent).groupedEvents).toHaveLength(4)
        expect((result[1] as InspectorListItemEvent).groupedEvents).toHaveLength(5)
    })

    it('sums durations when merging adjacent inactivity items', () => {
        const result = collapseAdjacentItems([makeInactivity(1000), makeInactivity(2000), makeInactivity(500)])
        expect(result).toHaveLength(1)
        expect((result[0] as InspectorListItemInactivity).durationMs).toBe(3500)
    })

    it('an inactivity item in between breaks the event run', () => {
        const items = [makeEvent(), makeEvent(), makeInactivity(1000), makeEvent(), makeEvent()]
        expect(collapseAdjacentItems(items)).toHaveLength(5)
    })

    it('keeps individual timestamps inside groupedEvents', () => {
        const events = Array.from({ length: 4 }, (_, i) => makeEvent({ timeInRecording: i * 1000, key: `event-${i}` }))
        const result = collapseAdjacentItems(events)
        const grouped = (result[0] as InspectorListItemEvent).groupedEvents!
        expect(grouped.map((e) => e.timeInRecording)).toEqual([0, 1000, 2000, 3000])
    })
})
