import {
    computeWrapperMinHeight,
    DEFAULT_BAR_SHADOW,
    HORIZONTAL_CHART_MARGIN_PX,
    HORIZONTAL_MIN_BAND_SIZE_DEFAULT,
    resolveBarShadow,
} from './bar-config'

describe('resolveBarShadow', () => {
    it('maps `true` to the default shadow', () => {
        expect(resolveBarShadow(true)).toBe(DEFAULT_BAR_SHADOW)
    })

    it.each([
        ['false', false],
        ['undefined', undefined],
    ])('maps `%s` to no shadow', (_desc, input) => {
        expect(resolveBarShadow(input as boolean | undefined)).toBeUndefined()
    })

    it('passes an explicit shadow config through untouched', () => {
        const shadow = { color: 'red', blur: 4, offsetX: 1, offsetY: 2 }
        expect(resolveBarShadow(shadow)).toBe(shadow)
    })
})

describe('computeWrapperMinHeight', () => {
    it('returns undefined for vertical charts', () => {
        expect(
            computeWrapperMinHeight({ isHorizontal: false, resolvedMinBandSize: 24, labels: ['a', 'b'] })
        ).toBeUndefined()
    })

    it('returns undefined when there is no band floor', () => {
        expect(
            computeWrapperMinHeight({ isHorizontal: true, resolvedMinBandSize: 0, labels: ['a', 'b'] })
        ).toBeUndefined()
    })

    it('returns undefined when there are no bands', () => {
        expect(computeWrapperMinHeight({ isHorizontal: true, resolvedMinBandSize: 24, labels: [] })).toBeUndefined()
    })

    it('reserves one band slot per unique label plus chart margins', () => {
        const labels = ['a', 'b', 'c']
        expect(
            computeWrapperMinHeight({
                isHorizontal: true,
                resolvedMinBandSize: HORIZONTAL_MIN_BAND_SIZE_DEFAULT,
                labels,
            })
        ).toBe(labels.length * HORIZONTAL_MIN_BAND_SIZE_DEFAULT + HORIZONTAL_CHART_MARGIN_PX)
    })

    it('counts unique bands only when labels repeat', () => {
        expect(computeWrapperMinHeight({ isHorizontal: true, resolvedMinBandSize: 10, labels: ['a', 'a', 'b'] })).toBe(
            2 * 10 + HORIZONTAL_CHART_MARGIN_PX
        )
    })
})
