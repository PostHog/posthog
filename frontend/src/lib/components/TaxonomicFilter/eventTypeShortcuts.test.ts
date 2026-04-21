import { AUTOCAPTURE_INTERACTIONS, buildEventTypeShortcuts } from './eventTypeShortcuts'

describe('buildEventTypeShortcuts', () => {
    it('returns no shortcuts for an empty query', () => {
        expect(buildEventTypeShortcuts({ searchQuery: '', includeEventName: true })).toEqual([])
        expect(buildEventTypeShortcuts({ searchQuery: '   ', includeEventName: false })).toEqual([])
    })

    it('returns no shortcuts when the query does not match any keyword', () => {
        expect(buildEventTypeShortcuts({ searchQuery: 'xyz', includeEventName: true })).toEqual([])
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
        const shortcuts = buildEventTypeShortcuts({ searchQuery, includeEventName: true })
        expect(shortcuts.map((s) => s.filterValue)).toEqual(matches)
    })

    it('matching is case-insensitive', () => {
        const upper = buildEventTypeShortcuts({ searchQuery: 'CLICK', includeEventName: true })
        const lower = buildEventTypeShortcuts({ searchQuery: 'click', includeEventName: true })
        expect(upper).toEqual(lower)
    })

    it('event-series shortcuts include eventName and label with "(autocapture)"', () => {
        const [clickShortcut] = buildEventTypeShortcuts({ searchQuery: 'click', includeEventName: true })
        expect(clickShortcut).toMatchObject({
            _type: 'quick_filter',
            name: 'Click (autocapture)',
            filterValue: 'click',
            propertyKey: '$event_type',
            eventName: '$autocapture',
        })
    })

    it('property-filter shortcuts omit eventName and label with "(event type)"', () => {
        const [clickShortcut] = buildEventTypeShortcuts({ searchQuery: 'click', includeEventName: false })
        expect(clickShortcut).toMatchObject({
            _type: 'quick_filter',
            name: 'Click (event type)',
            filterValue: 'click',
            propertyKey: '$event_type',
        })
        expect(clickShortcut.eventName).toBeUndefined()
    })

    it('covers every documented autocapture interaction with at least one keyword match', () => {
        for (const interaction of AUTOCAPTURE_INTERACTIONS) {
            const match = buildEventTypeShortcuts({
                searchQuery: interaction.keywords[0],
                includeEventName: true,
            })
            expect(match.some((s) => s.filterValue === interaction.eventType)).toBe(true)
        }
    })
})
