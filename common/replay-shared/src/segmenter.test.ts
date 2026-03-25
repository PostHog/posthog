import { mergeInactiveSegments } from './segmenter'
import { RecordingSegment } from './types'

function segment(overrides: Partial<RecordingSegment>): RecordingSegment {
    return {
        kind: 'window',
        startTimestamp: 0,
        endTimestamp: 1000,
        durationMs: 1000,
        windowId: 1,
        isActive: true,
        ...overrides,
    }
}

describe('mergeInactiveSegments', () => {
    it('returns empty array for empty input', () => {
        expect(mergeInactiveSegments([])).toEqual([])
    })

    it('passes through all-active segments unchanged', () => {
        const segments = [
            segment({ startTimestamp: 0, endTimestamp: 5000, isActive: true }),
            segment({ startTimestamp: 5000, endTimestamp: 10000, isActive: true }),
        ]
        expect(mergeInactiveSegments(segments)).toEqual(segments)
    })

    it('merges consecutive inactive segments into one', () => {
        const segments = [
            segment({ startTimestamp: 0, endTimestamp: 5000, isActive: false, kind: 'window' }),
            segment({ startTimestamp: 5000, endTimestamp: 10000, isActive: false, kind: 'gap' }),
            segment({ startTimestamp: 10000, endTimestamp: 15000, isActive: false, kind: 'buffer' }),
        ]

        const result = mergeInactiveSegments(segments)
        expect(result).toHaveLength(1)
        expect(result[0]).toMatchObject({
            kind: 'window',
            startTimestamp: 0,
            endTimestamp: 15000,
            durationMs: 15000,
            isActive: false,
        })
    })

    it('preserves alternating active/inactive pattern', () => {
        const segments = [
            segment({ startTimestamp: 0, endTimestamp: 5000, isActive: true }),
            segment({ startTimestamp: 5000, endTimestamp: 10000, isActive: false }),
            segment({ startTimestamp: 10000, endTimestamp: 15000, isActive: true }),
            segment({ startTimestamp: 15000, endTimestamp: 20000, isActive: false }),
        ]

        const result = mergeInactiveSegments(segments)
        expect(result).toHaveLength(4)
        expect(result.map((s) => s.isActive)).toEqual([true, false, true, false])
    })

    it('merges multiple runs of inactive segments between active ones', () => {
        const segments = [
            segment({ startTimestamp: 0, endTimestamp: 5000, isActive: true }),
            segment({ startTimestamp: 5000, endTimestamp: 8000, isActive: false }),
            segment({ startTimestamp: 8000, endTimestamp: 12000, isActive: false }),
            segment({ startTimestamp: 12000, endTimestamp: 17000, isActive: true }),
            segment({ startTimestamp: 17000, endTimestamp: 20000, isActive: false }),
            segment({ startTimestamp: 20000, endTimestamp: 25000, isActive: false }),
            segment({ startTimestamp: 25000, endTimestamp: 30000, isActive: false }),
        ]

        const result = mergeInactiveSegments(segments)
        expect(result).toHaveLength(4)
        expect(result[0]).toMatchObject({ startTimestamp: 0, endTimestamp: 5000, isActive: true })
        expect(result[1]).toMatchObject({
            startTimestamp: 5000,
            endTimestamp: 12000,
            isActive: false,
            durationMs: 7000,
        })
        expect(result[2]).toMatchObject({ startTimestamp: 12000, endTimestamp: 17000, isActive: true })
        expect(result[3]).toMatchObject({
            startTimestamp: 17000,
            endTimestamp: 30000,
            isActive: false,
            durationMs: 13000,
        })
    })

    it('handles single segment input', () => {
        const active = [segment({ isActive: true })]
        expect(mergeInactiveSegments(active)).toEqual(active)

        const inactive = [segment({ isActive: false, startTimestamp: 0, endTimestamp: 5000 })]
        const result = mergeInactiveSegments(inactive)
        expect(result).toHaveLength(1)
        expect(result[0].isActive).toBe(false)
    })

    it('uses kind from first segment in merged run', () => {
        const segments = [
            segment({ startTimestamp: 0, endTimestamp: 5000, isActive: false, kind: 'gap' }),
            segment({ startTimestamp: 5000, endTimestamp: 10000, isActive: false, kind: 'buffer' }),
        ]

        const result = mergeInactiveSegments(segments)
        expect(result[0].kind).toBe('gap')
    })
})
