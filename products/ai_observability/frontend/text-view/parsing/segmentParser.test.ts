import { getTruncatedSegmentIndices, parseTextSegments } from './segmentParser'

const truncatedMarker = (middle: string, count: number): string => `<<<TRUNCATED|${btoa(middle)}|${count}>>>`
const toolsMarker = (label: string, body: string): string => `<<<TOOLS_EXPANDABLE|${label}|${btoa(body)}>>>`
const genMarker = (eventId: string, label: string, body: string): string =>
    `<<<GEN_EXPANDABLE|${eventId}|${label}|${btoa(body)}>>>`

describe('getTruncatedSegmentIndices', () => {
    it('returns nothing when there are no markers', () => {
        expect(getTruncatedSegmentIndices('just some plain text')).toEqual([])
    })

    it('returns the index of a truncated segment', () => {
        const text = `start ${truncatedMarker('hidden middle', 4200)} end`
        const indices = getTruncatedSegmentIndices(text)

        expect(indices).toEqual([1])
        expect(parseTextSegments(text)[1].type).toBe('truncated')
    })

    it('returns only truncated indices, not structural expandables', () => {
        // Auto-expand must reveal truncated message content without expanding nested
        // generations or hidden tools, which would blow up the trace tree on load.
        const text = `a ${truncatedMarker('m', 10)} b ${toolsMarker('3 tools', 'tools')} c ${genMarker('evt', '[GEN]', 'gen')} d`
        const segments = parseTextSegments(text)
        const indices = getTruncatedSegmentIndices(text)

        expect(indices.map((i) => segments[i].type)).toEqual(['truncated'])
        expect(segments.some((s) => s.type === 'tools_expandable')).toBe(true)
        expect(segments.some((s) => s.type === 'gen_expandable')).toBe(true)
    })

    it('returns every truncated segment when there are several', () => {
        const text = `${truncatedMarker('one', 1)} between ${truncatedMarker('two', 2)}`
        const segments = parseTextSegments(text)
        const indices = getTruncatedSegmentIndices(text)

        expect(indices.every((i) => segments[i].type === 'truncated')).toBe(true)
        expect(indices).toHaveLength(2)
    })
})
