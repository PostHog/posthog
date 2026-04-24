import { getPromotedPropertyForEvent, hasTaxonomyPromotedProperty } from './promotedEventProperty'

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
