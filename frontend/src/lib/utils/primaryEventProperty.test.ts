import {
    getEventsWithPrimaryProperty,
    getPrimaryPropertyForEvent,
    hasTaxonomyPrimaryProperty,
} from './primaryEventProperty'

describe('getPrimaryPropertyForEvent', () => {
    it('returns the core taxonomy default for built-in events', () => {
        expect(getPrimaryPropertyForEvent('$pageview')).toBe('$pathname')
        expect(getPrimaryPropertyForEvent('$pageleave')).toBe('$pathname')
        expect(getPrimaryPropertyForEvent('$screen')).toBe('$screen_name')
        expect(getPrimaryPropertyForEvent('$feature_flag_called')).toBe('$feature_flag')
    })

    it('returns null for events with no taxonomy default and no override', () => {
        expect(getPrimaryPropertyForEvent('$autocapture')).toBeNull()
        expect(getPrimaryPropertyForEvent('some_custom_event')).toBeNull()
    })

    it('returns null for missing event names', () => {
        expect(getPrimaryPropertyForEvent(null)).toBeNull()
        expect(getPrimaryPropertyForEvent(undefined)).toBeNull()
        expect(getPrimaryPropertyForEvent('')).toBeNull()
    })

    it('ignores team-configured overrides for events that have a taxonomy default', () => {
        // Taxonomy is immutable — users can only set primary properties for events
        // without a fixed taxonomy entry.
        expect(getPrimaryPropertyForEvent('$pageview', { $pageview: '$current_url' })).toBe('$pathname')
        expect(getPrimaryPropertyForEvent('$screen', { $screen: 'my_custom_prop' })).toBe('$screen_name')
    })

    it('uses the team-configured override for custom events with no taxonomy default', () => {
        expect(getPrimaryPropertyForEvent('order_placed', { order_placed: 'order_id' })).toBe('order_id')
    })

    it('returns null when no override and no taxonomy default', () => {
        expect(getPrimaryPropertyForEvent('order_placed', { other_event: 'x' })).toBeNull()
    })
})

describe('getEventsWithPrimaryProperty', () => {
    it('returns events that have a taxonomy default', () => {
        const events = [
            { event: '$pageview', id: 1 },
            { event: '$autocapture', id: 2 },
            { event: '$screen', id: 3 },
        ]
        expect(getEventsWithPrimaryProperty(events)).toEqual([
            { event: '$pageview', id: 1 },
            { event: '$screen', id: 3 },
        ])
    })

    it('returns events that have a team override (no taxonomy default)', () => {
        const events = [
            { event: 'order_placed', id: 1 },
            { event: 'just_viewed', id: 2 },
        ]
        expect(getEventsWithPrimaryProperty(events, { order_placed: 'order_id' })).toEqual([
            { event: 'order_placed', id: 1 },
        ])
    })

    it('does not include events whose only override is on a taxonomy-fixed event', () => {
        // Taxonomy wins, so an attempted override on $pageview is moot — but the event is still
        // included because the taxonomy default already counts as a primary property.
        const events = [{ event: '$pageview', id: 1 }]
        expect(getEventsWithPrimaryProperty(events, { $pageview: '$current_url' })).toEqual(events)
    })

    it('returns an empty list when nothing has a primary property', () => {
        const events = [
            { event: '$autocapture', id: 1 },
            { event: 'arbitrary_custom', id: 2 },
        ]
        expect(getEventsWithPrimaryProperty(events)).toEqual([])
    })
})

describe('hasTaxonomyPrimaryProperty', () => {
    it('is true for built-in events that have a primary property', () => {
        expect(hasTaxonomyPrimaryProperty('$pageview')).toBe(true)
        expect(hasTaxonomyPrimaryProperty('$pageleave')).toBe(true)
        expect(hasTaxonomyPrimaryProperty('$screen')).toBe(true)
        expect(hasTaxonomyPrimaryProperty('$feature_flag_called')).toBe(true)
    })

    it('is false for events with no taxonomy primary property', () => {
        expect(hasTaxonomyPrimaryProperty('$autocapture')).toBe(false)
        expect(hasTaxonomyPrimaryProperty('order_placed')).toBe(false)
        expect(hasTaxonomyPrimaryProperty(null)).toBe(false)
        expect(hasTaxonomyPrimaryProperty(undefined)).toBe(false)
        expect(hasTaxonomyPrimaryProperty('')).toBe(false)
    })
})
