import { formatTooltipValue, TOOLTIP_EMPTY_VALUE } from './tooltipFormat'

describe('formatTooltipValue', () => {
    it.each([
        { name: 'NaN renders as the empty placeholder', value: NaN, expected: TOOLTIP_EMPTY_VALUE },
        { name: 'Infinity renders as the empty placeholder', value: Infinity, expected: TOOLTIP_EMPTY_VALUE },
        { name: '-Infinity renders as the empty placeholder', value: -Infinity, expected: TOOLTIP_EMPTY_VALUE },
    ])('$name', ({ value, expected }) => {
        expect(formatTooltipValue(value)).toBe(expected)
    })

    it('uses the provided formatter for finite values', () => {
        expect(formatTooltipValue(470, (v) => `${v}ms`)).toBe('470ms')
    })

    it('falls back to toLocaleString when no formatter is given', () => {
        // Assert against toLocaleString() rather than a hardcoded string so the test stays locale-stable.
        expect(formatTooltipValue(1234)).toBe((1234).toLocaleString())
    })

    it('does not swallow zero', () => {
        expect(formatTooltipValue(0)).toBe('0')
    })

    it('guards non-finite values before the formatter runs', () => {
        const formatter = jest.fn((v: number) => `${v}`)
        expect(formatTooltipValue(NaN, formatter)).toBe(TOOLTIP_EMPTY_VALUE)
        expect(formatter).not.toHaveBeenCalled()
    })
})
