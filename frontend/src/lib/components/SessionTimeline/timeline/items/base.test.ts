import { truncatePreviewTexts } from './base'

describe('truncatePreviewTexts', () => {
    it('returns original texts when already within the limit', () => {
        const result = truncatePreviewTexts({
            primaryText: 'Network request',
            secondaryText: 'POST /api/demo',
        })

        expect(result).toEqual({
            primaryText: 'Network request',
            secondaryText: 'POST /api/demo',
        })
    })

    it('truncates only primary text when no secondary text is provided', () => {
        const longPrimary = 'A'.repeat(340)

        const result = truncatePreviewTexts({
            primaryText: longPrimary,
        })

        expect(result.primaryText.length).toBeLessThanOrEqual(300)
        expect(result.primaryText.endsWith('…')).toBe(true)
        expect(result.secondaryText).toBeUndefined()
    })

    it('truncates primary and secondary text so the combined length stays within 300 chars', () => {
        const result = truncatePreviewTexts({
            primaryText: 'P'.repeat(170),
            secondaryText: 'S'.repeat(170),
        })

        expect(result.secondaryText).not.toBeUndefined()

        const combinedLength = result.primaryText.length + (result.secondaryText?.length ?? 0)
        expect(combinedLength).toBeLessThanOrEqual(300)
        expect(result.secondaryText?.endsWith('…')).toBe(true)
        expect(result.primaryText.length).toBeGreaterThan(result.secondaryText?.length ?? 0)
    })

    it('keeps short secondary text intact while truncating primary text', () => {
        const result = truncatePreviewTexts({
            primaryText: 'P'.repeat(360),
            secondaryText: 'short',
        })

        expect(result.secondaryText).toBe('short')
        expect(result.primaryText.length + (result.secondaryText?.length ?? 0)).toBeLessThanOrEqual(300)
    })

    it('allocates more text budget to primary text when both values are long', () => {
        const result = truncatePreviewTexts({
            primaryText: 'P'.repeat(500),
            secondaryText: 'S'.repeat(500),
        })

        expect(result.primaryText.length).toBeGreaterThan(result.secondaryText?.length ?? 0)
    })
})
