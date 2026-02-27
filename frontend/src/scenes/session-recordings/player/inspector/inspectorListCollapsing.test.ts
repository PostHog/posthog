import {
    InspectorListItemConsole,
    InspectorListItemEvent,
    InspectorListItemInactivity,
    computeDisplayGroups,
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

function counts(items: any[], groupSimilar = true): number[] {
    return computeDisplayGroups(items, groupSimilar).map((g) => g.indices.length)
}

describe('computeDisplayGroups', () => {
    it('returns empty for empty input', () => {
        expect(computeDisplayGroups([], true)).toEqual([])
    })

    it('does not group events across non-event items', () => {
        const items = [makeEvent(), makeEvent(), makeConsoleLog(), makeEvent()]
        expect(counts(items)).toEqual([2, 1, 1])
    })

    it('breaks event group on different event name or search text', () => {
        const items = [
            makeEvent({ search: 'Clicked A' }),
            makeEvent({ search: 'Clicked A' }),
            makeEvent({ search: 'Clicked B' }),
        ]
        expect(counts(items)).toEqual([2, 1])
    })

    it('groups highlighted events with same highlight color', () => {
        const items = [makeEvent({ highlightColor: 'primary' }), makeEvent({ highlightColor: 'primary' }), makeEvent()]
        expect(counts(items)).toEqual([2, 1])
    })

    it('breaks event group on different highlight color', () => {
        const items = [makeEvent({ highlightColor: 'danger' }), makeEvent({ highlightColor: 'primary' })]
        expect(counts(items)).toEqual([1, 1])
    })

    it('groups adjacent console logs with same content and highlight', () => {
        const items = [makeConsoleLog(), makeConsoleLog(), makeConsoleLog()]
        expect(counts(items)).toEqual([3])
    })

    it('does not group console logs across non-console items', () => {
        const items = [makeConsoleLog(), makeEvent(), makeConsoleLog()]
        expect(counts(items)).toEqual([1, 1, 1])
    })

    it('breaks console log group on different content or highlight', () => {
        const items = [
            makeConsoleLog({ highlightColor: 'danger' }),
            makeConsoleLog({ highlightColor: 'danger' }),
            makeConsoleLog({ highlightColor: 'warning' }),
        ]
        expect(counts(items)).toEqual([2, 1])
    })

    it('disables all grouping when groupSimilar is false', () => {
        const items = [makeEvent(), makeEvent(), makeConsoleLog(), makeConsoleLog()]
        expect(counts(items, false)).toEqual([1, 1, 1, 1])
    })

    it('does not group inactivity items', () => {
        const inactivity: InspectorListItemInactivity = {
            type: 'inactivity',
            timestamp: {} as any,
            timeInRecording: 1000,
            search: '',
            key: 'i',
            durationMs: 5000,
        }
        expect(counts([inactivity, inactivity])).toEqual([1, 1])
    })

    it('tracks correct indices', () => {
        const items = [makeEvent(), makeEvent(), makeConsoleLog(), makeConsoleLog()]
        const groups = computeDisplayGroups(items, true)
        expect(groups).toEqual([{ indices: [0, 1] }, { indices: [2, 3] }])
    })
})
