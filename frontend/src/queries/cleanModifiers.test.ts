import { cleanModifiers } from './cleanModifiers'

describe('cleanModifiers', () => {
    it('returns primitives unchanged', () => {
        expect(cleanModifiers(null)).toBeNull()
        expect(cleanModifiers(undefined)).toBeUndefined()
        expect(cleanModifiers(42)).toBe(42)
        expect(cleanModifiers('foo')).toBe('foo')
        expect(cleanModifiers(true)).toBe(true)
    })

    it('strips usePresortedEventsTable from top-level modifiers', () => {
        const input = {
            kind: 'EventsQuery',
            modifiers: { usePresortedEventsTable: true, inCohortVia: 'subquery' },
        }
        expect(cleanModifiers(input)).toEqual({
            kind: 'EventsQuery',
            modifiers: { inCohortVia: 'subquery' },
        })
    })

    it('strips usePresortedEventsTable from nested source.modifiers', () => {
        const input = {
            kind: 'DataTableNode',
            source: {
                kind: 'EventsQuery',
                modifiers: { usePresortedEventsTable: false },
                select: ['*'],
            },
        }
        expect(cleanModifiers(input)).toEqual({
            kind: 'DataTableNode',
            source: {
                kind: 'EventsQuery',
                modifiers: {},
                select: ['*'],
            },
        })
    })

    it('preserves other modifier keys and unrelated fields', () => {
        const input = {
            kind: 'TrendsQuery',
            modifiers: { usePresortedEventsTable: true, personsOnEventsMode: 'disabled', debug: true },
            series: [{ event: 'pageview', kind: 'EventsNode' }],
            dateRange: { date_from: '-7d' },
        }
        expect(cleanModifiers(input)).toEqual({
            kind: 'TrendsQuery',
            modifiers: { personsOnEventsMode: 'disabled', debug: true },
            series: [{ event: 'pageview', kind: 'EventsNode' }],
            dateRange: { date_from: '-7d' },
        })
    })

    it('does not mutate the input', () => {
        const input = {
            kind: 'EventsQuery',
            modifiers: { usePresortedEventsTable: true, inCohortVia: 'subquery' },
        }
        const snapshot = JSON.parse(JSON.stringify(input))
        cleanModifiers(input)
        expect(input).toEqual(snapshot)
    })

    it('does not strip non-modifier keys with the same name as a deprecated modifier', () => {
        const input = {
            kind: 'EventsQuery',
            properties: { usePresortedEventsTable: true },
        }
        expect(cleanModifiers(input)).toEqual(input)
    })

    it('handles arrays of nodes', () => {
        const input = [
            { kind: 'EventsQuery', modifiers: { usePresortedEventsTable: true } },
            { kind: 'EventsQuery', modifiers: { inCohortVia: 'subquery' } },
        ]
        expect(cleanModifiers(input)).toEqual([
            { kind: 'EventsQuery', modifiers: {} },
            { kind: 'EventsQuery', modifiers: { inCohortVia: 'subquery' } },
        ])
    })

    it('leaves modifiers untouched when not an object', () => {
        // `modifiers` should always be an object, but guard against malformed URL state.
        const input = { kind: 'EventsQuery', modifiers: null }
        expect(cleanModifiers(input)).toEqual({ kind: 'EventsQuery', modifiers: null })
    })
})
