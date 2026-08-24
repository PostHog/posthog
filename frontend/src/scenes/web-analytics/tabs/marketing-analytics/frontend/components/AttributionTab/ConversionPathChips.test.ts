import { collapseConsecutive } from './ConversionPathChips'

describe('collapseConsecutive', () => {
    it('returns an empty list for an empty path', () => {
        expect(collapseConsecutive([])).toEqual([])
    })

    it('keeps distinct steps as-is', () => {
        expect(collapseConsecutive(['google', 'newsletter', 'direct'])).toEqual([
            { value: 'google', count: 1 },
            { value: 'newsletter', count: 1 },
            { value: 'direct', count: 1 },
        ])
    })

    it('collapses consecutive repeats into a count', () => {
        expect(collapseConsecutive(['google', 'google', 'google'])).toEqual([{ value: 'google', count: 3 }])
    })

    it('only collapses adjacent repeats, not the same value elsewhere in the journey', () => {
        expect(collapseConsecutive(['google', 'google', 'direct', 'google'])).toEqual([
            { value: 'google', count: 2 },
            { value: 'direct', count: 1 },
            { value: 'google', count: 1 },
        ])
    })

    it('collapses empty-string steps too, since "(none)" journeys repeat like any other', () => {
        expect(collapseConsecutive(['', '', 'google'])).toEqual([
            { value: '', count: 2 },
            { value: 'google', count: 1 },
        ])
    })
})
