import { formatDefinitionCount, formatDefinitionCountDelta, isCappedDefinitionCount } from './definitionCount'

describe('definitionCount', () => {
    it.each([
        [0, '0'],
        [9_999, '9999'],
        [10_000, '10,000+'],
        [25_000, '25000'],
    ])('formats a count of %i as %s', (count, expected) => {
        expect(formatDefinitionCount(count)).toBe(expected)
        expect(isCappedDefinitionCount(count)).toBe(count === 10_000)
    })

    it.each([
        [310, 100, '210'],
        [10_000, 100, '9,900+'],
        [25_000, 100, '24,900'],
        [50, 100, '0'],
    ])('formats the rows beyond the page for a total of %i with %i shown as %s', (total, shown, expected) => {
        expect(formatDefinitionCountDelta(total, shown)).toBe(expected)
    })
})
