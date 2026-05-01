import {
    getEventsWithPromotedProperty,
    getPromotedPropertyForEvent,
    hasTaxonomyPromotedProperty,
} from './promotedEventProperty'

describe('getPromotedPropertyForEvent', () => {
    it('returns the core taxonomy default for built-in events', () => {
        expect(getPromotedPropertyForEvent('$pageview')).toBe('$pathname')
        expect(getPromotedPropertyForEvent('$pageleave')).toBe('$pathname')
        expect(getPromotedPropertyForEvent('$screen')).toBe('$screen_name')
        expect(getPromotedPropertyForEvent('$feature_flag_called')).toBe('$feature_flag')
    })

    it('returns null for events with no taxonomy default and no override', () => {
        expect(getPromotedPropertyForEvent('$autocapture')).toBeNull()
        expect(getPromotedPropertyForEvent('some_custom_event')).toBeNull()
    })

    it('returns null for missing event names', () => {
        expect(getPromotedPropertyForEvent(null)).toBeNull()
        expect(getPromotedPropertyForEvent(undefined)).toBeNull()
        expect(getPromotedPropertyForEvent('')).toBeNull()
    })

    it('ignores team-configured overrides for events that have a taxonomy default', () => {
        // Taxonomy is immutable — users can only promote properties for events
        // without a fixed taxonomy entry.
        expect(getPromotedPropertyForEvent('$pageview', { $pageview: '$current_url' })).toBe('$pathname')
        expect(getPromotedPropertyForEvent('$screen', { $screen: 'my_custom_prop' })).toBe('$screen_name')
    })

    it('uses the team-configured override for custom events with no taxonomy default', () => {
        expect(getPromotedPropertyForEvent('order_placed', { order_placed: 'order_id' })).toBe('order_id')
    })

    it('returns null when no override and no taxonomy default', () => {
        expect(getPromotedPropertyForEvent('order_placed', { other_event: 'x' })).toBeNull()
    })
})

describe('getEventsWithPromotedProperty', () => {
    it('returns events that have a taxonomy default', () => {
        const events = [
            { event: '$pageview', id: 1 },
            { event: '$autocapture', id: 2 },
            { event: '$screen', id: 3 },
        ]
        expect(getEventsWithPromotedProperty(events)).toEqual([
            { event: '$pageview', id: 1 },
            { event: '$screen', id: 3 },
        ])
    })

    it('returns events that have a team override (no taxonomy default)', () => {
        const events = [
            { event: 'order_placed', id: 1 },
            { event: 'just_viewed', id: 2 },
        ]
        expect(getEventsWithPromotedProperty(events, { order_placed: 'order_id' })).toEqual([
            { event: 'order_placed', id: 1 },
        ])
    })

    it('does not include events whose only override is on a taxonomy-fixed event', () => {
        // Taxonomy wins, so an attempted override on $pageview is moot — but the event is still
        // included because the taxonomy default already counts as a promoted property.
        const events = [{ event: '$pageview', id: 1 }]
        expect(getEventsWithPromotedProperty(events, { $pageview: '$current_url' })).toEqual(events)
    })

    it('returns an empty list when nothing has a promoted property', () => {
        const events = [
            { event: '$autocapture', id: 1 },
            { event: 'arbitrary_custom', id: 2 },
        ]
        expect(getEventsWithPromotedProperty(events)).toEqual([])
    })
})

describe('hasTaxonomyPromotedProperty', () => {
    it('is true for built-in events that have a promoted property', () => {
        expect(hasTaxonomyPromotedProperty('$pageview')).toBe(true)
        expect(hasTaxonomyPromotedProperty('$pageleave')).toBe(true)
        expect(hasTaxonomyPromotedProperty('$screen')).toBe(true)
        expect(hasTaxonomyPromotedProperty('$feature_flag_called')).toBe(true)
    })

    it('is false for events with no taxonomy promoted property', () => {
        expect(hasTaxonomyPromotedProperty('$autocapture')).toBe(false)
        expect(hasTaxonomyPromotedProperty('order_placed')).toBe(false)
        expect(hasTaxonomyPromotedProperty(null)).toBe(false)
        expect(hasTaxonomyPromotedProperty(undefined)).toBe(false)
        expect(hasTaxonomyPromotedProperty('')).toBe(false)
    })
})
