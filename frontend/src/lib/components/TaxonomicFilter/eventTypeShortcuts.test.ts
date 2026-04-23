import { eventTypeToVerb } from 'lib/utils'

import {
    AUTOCAPTURE_INTERACTIONS,
    MIN_SHORTCUT_QUERY_LENGTH,
    buildAutocaptureSeriesShortcuts,
    buildEventTypeFilterShortcuts,
} from './eventTypeShortcuts'

describe('event type shortcuts', () => {
    describe('buildAutocaptureSeriesShortcuts', () => {
        it.each([
            ['empty', ''],
            ['whitespace only', '   '],
            ['one char', 'c'],
            ['two chars', 'cl'],
        ])('returns no shortcuts for %s queries', (_, searchQuery) => {
            expect(buildAutocaptureSeriesShortcuts(searchQuery)).toEqual([])
        })

        it('returns no shortcuts when the query does not match any keyword', () => {
            expect(buildAutocaptureSeriesShortcuts('xyzabc')).toEqual([])
        })

        it.each([
            { searchQuery: 'click', matches: ['click'] },
            { searchQuery: 'clicked', matches: ['click'] },
            { searchQuery: 'tap', matches: ['click'] },
            { searchQuery: 'submit', matches: ['submit'] },
            { searchQuery: 'form', matches: ['submit'] },
            { searchQuery: 'chan', matches: ['change'] },
            { searchQuery: 'scr', matches: ['scroll'] },
            { searchQuery: 'long', matches: ['long_press'] },
        ])('maps "$searchQuery" to shortcut(s) for $matches', ({ searchQuery, matches }) => {
            expect(buildAutocaptureSeriesShortcuts(searchQuery).map((s) => s.filterValue)).toEqual(matches)
        })

        it('matching is case-insensitive', () => {
            expect(buildAutocaptureSeriesShortcuts('CLICK')).toEqual(buildAutocaptureSeriesShortcuts('click'))
        })

        it('includes $autocapture as eventName and labels with "(autocapture)"', () => {
            const [clickShortcut] = buildAutocaptureSeriesShortcuts('click')
            expect(clickShortcut).toMatchObject({
                _type: 'quick_filter',
                name: 'Click (autocapture)',
                filterValue: 'click',
                propertyKey: '$event_type',
                eventName: '$autocapture',
            })
        })
    })

    describe('buildEventTypeFilterShortcuts', () => {
        it('omits eventName and labels with "(event type)"', () => {
            const [clickShortcut] = buildEventTypeFilterShortcuts('click')
            expect(clickShortcut).toMatchObject({
                _type: 'quick_filter',
                name: 'Click (event type)',
                filterValue: 'click',
                propertyKey: '$event_type',
            })
            expect(clickShortcut.eventName).toBeUndefined()
        })

        it('honours the same min-length guard as the series variant', () => {
            expect(buildEventTypeFilterShortcuts('c')).toEqual([])
            expect(buildEventTypeFilterShortcuts('cl')).toEqual([])
            expect(buildEventTypeFilterShortcuts('cli').length).toBeGreaterThan(0)
        })
    })

    describe('keyword coverage', () => {
        it('every keyword of every interaction surfaces its shortcut (via both builders)', () => {
            for (const interaction of AUTOCAPTURE_INTERACTIONS) {
                for (const keyword of interaction.keywords) {
                    if (keyword.length < MIN_SHORTCUT_QUERY_LENGTH) {
                        continue
                    }
                    const series = buildAutocaptureSeriesShortcuts(keyword)
                    expect(series.some((s) => s.filterValue === interaction.eventType)).toBe(true)
                    const filter = buildEventTypeFilterShortcuts(keyword)
                    expect(filter.some((s) => s.filterValue === interaction.eventType)).toBe(true)
                }
            }
        })

        it('AUTOCAPTURE_INTERACTIONS eventTypes match the canonical eventTypeToVerb keys', () => {
            const shortcutKeys = AUTOCAPTURE_INTERACTIONS.map((i) => i.eventType).sort()
            const canonicalKeys = Object.keys(eventTypeToVerb).sort()
            expect(shortcutKeys).toEqual(canonicalKeys)
        })
    })
})
