import { eventTypeToVerb } from 'lib/utils'

import {
    AUTOCAPTURE_INTERACTIONS,
    MAX_SHORTCUT_MATCHES,
    buildAutocaptureSeriesShortcuts,
    buildEventTypeFilterShortcuts,
} from './eventTypeShortcuts'

describe('event type shortcuts', () => {
    describe('buildAutocaptureSeriesShortcuts', () => {
        it.each([
            ['empty', ''],
            ['whitespace only', '   '],
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
            { searchQuery: 'cl', matches: ['click'] }, // 2 chars narrows to a single interaction
            { searchQuery: 'ch', matches: ['change'] },
        ])('maps "$searchQuery" to shortcut(s) for $matches', ({ searchQuery, matches }) => {
            expect(buildAutocaptureSeriesShortcuts(searchQuery).map((s) => s.filterValue)).toEqual(matches)
        })

        it('matching is case-insensitive', () => {
            expect(buildAutocaptureSeriesShortcuts('CLICK')).toEqual(buildAutocaptureSeriesShortcuts('click'))
        })

        it('suppresses shortcuts when the query matches too many distinct interactions', () => {
            // 's' prefix hits submit, scroll, swipe, and toggle (via 'switch') — too ambiguous.
            const shortcuts = buildAutocaptureSeriesShortcuts('s')
            expect(shortcuts).toEqual([])
        })

        it('re-surfaces shortcuts as the user narrows the query', () => {
            expect(buildAutocaptureSeriesShortcuts('s')).toEqual([])
            expect(buildAutocaptureSeriesShortcuts('sw').length).toBeGreaterThan(0) // swipe + toggle-via-switch
            expect(buildAutocaptureSeriesShortcuts('swipe').map((s) => s.filterValue)).toEqual(['swipe'])
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

        it('honours the same ambiguity cap as the series variant', () => {
            // 't' is ambiguous (click-via-tap, touch, toggle, change-via-typed) — suppressed
            expect(buildEventTypeFilterShortcuts('t')).toEqual([])
            // 'tap' narrows to click — surfaces
            expect(buildEventTypeFilterShortcuts('tap')).toHaveLength(1)
        })
    })

    describe('ambiguity cap enforcement', () => {
        it.each([
            ['s', 'submit/scroll/swipe/toggle-via-switch'],
            ['t', 'click-via-tap/touch/toggle/change-via-typed'],
        ])('single-char "%s" (%s) matches too many interactions and is suppressed', (query) => {
            expect(buildAutocaptureSeriesShortcuts(query).length).toBeLessThanOrEqual(0)
        })

        it('never surfaces more than MAX_SHORTCUT_MATCHES shortcuts for any query', () => {
            const seenPrefixes = new Set<string>()
            for (const interaction of AUTOCAPTURE_INTERACTIONS) {
                for (const keyword of interaction.keywords) {
                    for (let i = 1; i <= keyword.length; i++) {
                        seenPrefixes.add(keyword.slice(0, i))
                    }
                }
            }
            for (const prefix of seenPrefixes) {
                expect(buildAutocaptureSeriesShortcuts(prefix).length).toBeLessThanOrEqual(MAX_SHORTCUT_MATCHES)
            }
        })
    })

    describe('keyword coverage', () => {
        it('every full keyword surfaces its interaction (via both builders)', () => {
            for (const interaction of AUTOCAPTURE_INTERACTIONS) {
                for (const keyword of interaction.keywords) {
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
