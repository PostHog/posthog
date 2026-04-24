import { getPromotedPropertyForEvent } from './promotedEventProperty'

describe('getPromotedPropertyForEvent', () => {
    it('returns the core taxonomy default for built-in events', () => {
        expect(getPromotedPropertyForEvent('$pageview')).toBe('$current_url')
        expect(getPromotedPropertyForEvent('$pageleave')).toBe('$current_url')
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

    it('prefers the team-configured override over the taxonomy default', () => {
        expect(getPromotedPropertyForEvent('$pageview', { $pageview: '$pathname' })).toBe('$pathname')
    })

    it('uses the team-configured override for custom events with no taxonomy default', () => {
        expect(getPromotedPropertyForEvent('order_placed', { order_placed: 'order_id' })).toBe('order_id')
    })

    it('falls back to the taxonomy default when the override map has no matching entry', () => {
        expect(getPromotedPropertyForEvent('$pageview', { other_event: 'x' })).toBe('$current_url')
    })
})
