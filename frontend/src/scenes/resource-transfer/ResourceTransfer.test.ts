import { sourceResourceUrl } from './ResourceTransfer'

describe('resource transfer back link', () => {
    it('returns to the source insight using its short id', () => {
        expect(sourceResourceUrl('Insight', '42', 'abc123')).toBe('/insights/abc123')
    })

    it('returns to the insights list when a direct transfer URL has no short id', () => {
        expect(sourceResourceUrl('Insight', '42')).toBe('/insights')
    })

    it('returns to other resource pages using their numeric ids', () => {
        expect(sourceResourceUrl('Dashboard', '42')).toBe('/dashboard/42')
    })
})
