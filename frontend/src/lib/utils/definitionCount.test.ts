import { formatDefinitionCount, formatDefinitionCountDelta } from './definitionCount'

describe('definitionCount', () => {
    it.each([
        [0, false, '0'],
        [9_999, false, '9,999'],
        [10_000, true, '10,000+'],
        [10_000, false, '10,000'],
        [25_000, false, '25,000'],
    ])('formats a count of %i (capped: %s) as %s', (count, isCapped, expected) => {
        expect(formatDefinitionCount(count, isCapped)).toBe(expected)
    })

    it.each([
        [310, 100, false, '210'],
        [10_000, 100, true, '9,900+'],
        [10_000, 100, false, '9,900'],
        [50, 100, false, '0'],
    ])(
        'formats the rows beyond the page for a total of %i with %i shown (capped: %s) as %s',
        (total, shown, isCapped, expected) => {
            expect(formatDefinitionCountDelta(total, shown, isCapped)).toBe(expected)
        }
    )

    it.each([[undefined as unknown as number], [null as unknown as number], [NaN]])(
        'renders a missing count as 0 rather than throwing on %p',
        (count) => {
            expect(() => formatDefinitionCount(count, false)).not.toThrow()
            expect(formatDefinitionCount(count, false)).toBe('0')
        }
    )
})
