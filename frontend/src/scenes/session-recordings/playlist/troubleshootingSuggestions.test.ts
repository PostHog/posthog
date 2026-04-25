import { nextWideningSuggestion } from './troubleshootingSuggestions'

describe('nextWideningSuggestion()', () => {
    it.each([
        ['-1h', '-7d'],
        ['-12h', '-7d'],
        ['-24h', '-7d'],
        ['-1d', '-7d'],
    ])('widens small windows to 7 days: %s -> %s', (dateFrom, expected) => {
        expect(nextWideningSuggestion(dateFrom)?.value).toBe(expected)
    })

    it.each([
        ['-2d', '-30d'],
        ['-3d', '-30d'],
        ['-7d', '-30d'],
        ['-14d', '-30d'],
        ['-1w', '-30d'],
        ['-29d', '-30d'],
    ])('widens mid-range windows to 30 days: %s -> %s', (dateFrom, expected) => {
        expect(nextWideningSuggestion(dateFrom)?.value).toBe(expected)
    })

    it.each([['-30d'], ['-60d'], ['-1y'], ['-5y']])(
        'does not suggest further widening when already at 30d or beyond: %s',
        (dateFrom) => {
            expect(nextWideningSuggestion(dateFrom)).toBeNull()
        }
    )

    it.each([[null], [undefined], ['2024-01-01'], ['-3.5d'], ['garbage']])(
        'falls back to 30 days for unparseable or missing date_from: %s',
        (dateFrom) => {
            expect(nextWideningSuggestion(dateFrom as string | null | undefined)?.value).toBe('-30d')
        }
    )
})
