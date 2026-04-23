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
            // direct eventType matches
            { searchQuery: 'click', matches: ['click'] },
            { searchQuery: 'submit', matches: ['submit'] },
            { searchQuery: 'scroll', matches: ['scroll'] },
            { searchQuery: 'pinch', matches: ['pinch'] },
            // past-tense verb matches (from eventTypeToVerb values)
            { searchQuery: 'clicked', matches: ['click'] },
            { searchQuery: 'submitted', matches: ['submit'] },
            { searchQuery: 'rotated', matches: ['rotation'] },
            { searchQuery: 'long pressed', matches: ['long_press'] },
            // prefix narrowing to a single interaction
            { searchQuery: 'scr', matches: ['scroll'] },
            { searchQuery: 'long', matches: ['long_press'] },
            { searchQuery: 'pin', matches: ['pinch'] },
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

        it('change interaction matches both "change" and "changed" (the verb)', () => {
            expect(buildAutocaptureSeriesShortcuts('change').map((s) => s.filterValue)).toContain('change')
            expect(buildAutocaptureSeriesShortcuts('changed').map((s) => s.filterValue)).toContain('change')
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
    })

    describe('ambiguity cap enforcement', () => {
        it('never surfaces more than MAX_SHORTCUT_MATCHES shortcuts for any possible prefix', () => {
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

    describe('derivation from eventTypeToVerb', () => {
        it('every interaction has keywords including at least the eventType and derived label', () => {
            for (const interaction of AUTOCAPTURE_INTERACTIONS) {
                expect(interaction.keywords).toContain(interaction.eventType)
                expect(interaction.keywords).toContain(interaction.label.toLowerCase())
            }
        })

        it('every keyword surfaces its interaction (via both builders)', () => {
            for (const interaction of AUTOCAPTURE_INTERACTIONS) {
                for (const keyword of interaction.keywords) {
                    const series = buildAutocaptureSeriesShortcuts(keyword)
                    expect(series.some((s) => s.filterValue === interaction.eventType)).toBe(true)
                    const filter = buildEventTypeFilterShortcuts(keyword)
                    expect(filter.some((s) => s.filterValue === interaction.eventType)).toBe(true)
                }
            }
        })

        it('every canonical eventTypeToVerb key is represented', () => {
            const derivedEventTypes = new Set(AUTOCAPTURE_INTERACTIONS.map((i) => i.eventType))
            expect(derivedEventTypes).toEqual(new Set(Object.keys(eventTypeToVerb)))
        })

        it('label is capitalized and eventType appears in keywords', () => {
            for (const interaction of AUTOCAPTURE_INTERACTIONS) {
                expect(interaction.label).toMatch(/^[A-Z]/)
                expect(interaction.keywords).toContain(interaction.eventType)
            }
        })
    })
})
