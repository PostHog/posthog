import { DEFAULT_MARGINS, X_AXIS_TITLE_MARGIN } from '../../../core/hooks/useChartMargins'
import { computeWrapperMinHeight, HORIZONTAL_MIN_BAND_SIZE_DEFAULT, resolveBarShadow } from './bar-config'

const CHART_MARGIN_PX = DEFAULT_MARGINS.top + DEFAULT_MARGINS.bottom + X_AXIS_TITLE_MARGIN

describe('bar-config', () => {
    describe('resolveBarShadow', () => {
        it('returns the default upward shadow when true', () => {
            expect(resolveBarShadow(true)).toEqual({ color: 'rgba(0,0,0,0.30)', blur: 12, offsetY: -4 })
        })

        it.each([
            { desc: 'false', value: false as const },
            { desc: 'undefined', value: undefined },
        ])('returns undefined when $desc', ({ value }) => {
            expect(resolveBarShadow(value)).toBeUndefined()
        })

        it('passes an explicit shadow object through unchanged', () => {
            const custom = { color: 'red', blur: 2, offsetX: 1, offsetY: 3 }
            expect(resolveBarShadow(custom)).toBe(custom)
        })
    })

    describe('computeWrapperMinHeight', () => {
        const base = {
            isHorizontal: true,
            fitToHeight: false,
            resolvedMinBandSize: HORIZONTAL_MIN_BAND_SIZE_DEFAULT,
            labels: ['a', 'b', 'c'],
        }

        it.each([
            {
                desc: '3 distinct labels',
                labels: ['a', 'b', 'c'],
                expected: 3 * HORIZONTAL_MIN_BAND_SIZE_DEFAULT + CHART_MARGIN_PX,
            },
            {
                desc: 'duplicate labels counted once',
                labels: ['a', 'a', 'b'],
                expected: 2 * HORIZONTAL_MIN_BAND_SIZE_DEFAULT + CHART_MARGIN_PX,
            },
        ])('reserves the min band size per unique band plus chart margins ($desc)', ({ labels, expected }) => {
            expect(computeWrapperMinHeight({ ...base, labels })).toBe(expected)
        })

        it.each([
            { desc: 'vertical', override: { isHorizontal: false } },
            { desc: 'fit-to-height', override: { fitToHeight: true } },
            { desc: 'min band size is zero', override: { resolvedMinBandSize: 0 } },
            { desc: 'there are no bands', override: { labels: [] } },
        ])('returns undefined when $desc', ({ override }) => {
            expect(computeWrapperMinHeight({ ...base, ...override })).toBeUndefined()
        })
    })
})
