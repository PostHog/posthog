import {
    autoFormatYTick,
    computePercentStackData,
    computeStackData,
    createScales,
    createXScale,
    createYScale,
} from '../core/scales'
import { DEFAULT_Y_AXIS_ID } from '../core/types'
import { dimensions, makeSeries } from '../test-helpers'

describe('hog-charts scales', () => {
    describe('createXScale', () => {
        it('maps the first label to plotLeft', () => {
            const scale = createXScale(['a', 'b', 'c'], dimensions)
            expect(scale('a')).toBe(dimensions.plotLeft)
        })

        it('maps the last label to plotLeft + plotWidth', () => {
            const scale = createXScale(['a', 'b', 'c'], dimensions)
            expect(scale('c')).toBe(dimensions.plotLeft + dimensions.plotWidth)
        })

        it('spaces three labels evenly across the plot area', () => {
            const scale = createXScale(['a', 'b', 'c'], dimensions)
            const a = scale('a')!
            const b = scale('b')!
            const c = scale('c')!
            expect(b - a).toBeCloseTo(c - b, 5)
        })

        it('returns undefined for a label not in the domain', () => {
            const scale = createXScale(['a', 'b'], dimensions)
            expect(scale('z')).toBeUndefined()
        })

        it('handles a single label placed at the center of the range', () => {
            // d3 scalePoint with a single domain element and no padding places it at
            // the midpoint of the range, not at range[0]
            const scale = createXScale(['only'], dimensions)
            const expected = dimensions.plotLeft + dimensions.plotWidth / 2
            expect(scale('only')).toBeCloseTo(expected, 5)
        })

        it('returns an empty domain for an empty labels array', () => {
            const scale = createXScale([], dimensions)
            expect(scale.domain()).toEqual([])
        })
    })

    describe('createYScale — linear mode', () => {
        it('maps maximum value to the top of the plot area (plotTop)', () => {
            const series = [makeSeries({ key: 's1', data: [0, 50, 100] })]
            const scale = createYScale(series, dimensions)
            // nice() may adjust the domain, so just verify direction
            const yAtMax = scale(100)
            const yAtMin = scale(0)
            expect(yAtMax).toBeLessThan(yAtMin)
        })

        it('adjusts minimum to 0 when all values are positive', () => {
            const series = [makeSeries({ key: 's1', data: [10, 20, 30] })]
            const scale = createYScale(series, dimensions)
            const [domainMin] = scale.domain()
            expect(domainMin).toBe(0)
        })

        it('preserves negative minimum when data has negative values', () => {
            const series = [makeSeries({ key: 's1', data: [-10, 0, 10] })]
            const scale = createYScale(series, dimensions)
            const [domainMin] = scale.domain()
            expect(domainMin).toBeLessThan(0)
        })

        it('extends max to 0 when all values are negative (mirror of positive-data zero baseline)', () => {
            const series = [makeSeries({ key: 's1', data: [-30, -20, -10] })]
            const scale = createYScale(series, dimensions)
            const [, domainMax] = scale.domain()
            expect(domainMax).toBe(0)
        })

        it('returns a fallback [0,1] domain for empty series', () => {
            const scale = createYScale([], dimensions)
            expect(scale.domain()).toEqual([0, 1])
        })

        it('returns a fallback [0,1] domain when all values are null-like', () => {
            const series = [makeSeries({ key: 's1', data: [NaN, Infinity, -Infinity] })]
            const scale = createYScale(series, dimensions)
            expect(scale.domain()).toEqual([0, 1])
        })

        it('excludes visibility.excluded series from the domain calculation', () => {
            const visible = makeSeries({ key: 'v', data: [0, 10] })
            const hidden = makeSeries({ key: 'h', data: [0, 1000], visibility: { excluded: true } })
            const scale = createYScale([visible, hidden], dimensions)
            const domainMax = scale.domain()[1]
            // nice() can extend the domain slightly, but it should be nowhere near 1000
            expect(domainMax).toBeLessThan(100)
        })

        it('maps the output range from plotTop + plotHeight down to plotTop', () => {
            const series = [makeSeries({ key: 's1', data: [0, 100] })]
            const scale = createYScale(series, dimensions)
            const [rangeMax, rangeMin] = scale.range()
            expect(rangeMax).toBe(dimensions.plotTop + dimensions.plotHeight)
            expect(rangeMin).toBe(dimensions.plotTop)
        })
    })

    describe('createYScale — log mode', () => {
        it('returns a log scale', () => {
            const series = [makeSeries({ key: 's1', data: [1, 10, 100] })]
            const scale = createYScale(series, dimensions, { scaleType: 'log' })
            expect('base' in scale).toBe(true)
        })

        it('clamps minimum to 1e-10 to avoid log(0)', () => {
            const series = [makeSeries({ key: 's1', data: [0, 10, 100] })]
            const scale = createYScale(series, dimensions, { scaleType: 'log' })
            const [domainMin] = scale.domain()
            expect(domainMin).toBeGreaterThanOrEqual(1e-10)
        })

        it('maps higher values to lower pixel positions (top of chart)', () => {
            const series = [makeSeries({ key: 's1', data: [1, 100] })]
            const scale = createYScale(series, dimensions, { scaleType: 'log' })
            expect(scale(100)).toBeLessThan(scale(1))
        })

        it('falls back to a linear scale when all data is non-positive (log undefined)', () => {
            const series = [makeSeries({ key: 's1', data: [-100, -50, -10] })]
            const scale = createYScale(series, dimensions, { scaleType: 'log' })
            // Linear domain spans the data; not collapsed to a 1e-10 single point.
            const [domainMin, domainMax] = scale.domain()
            expect(domainMin).toBeLessThan(domainMax)
            // The fallback is linear, so different inputs produce different outputs (not collapsed).
            expect(scale(-100)).not.toBeCloseTo(scale(-10), 0)
        })
    })

    describe('createYScale — percent stack mode', () => {
        it('uses a fixed [0, 1] domain regardless of series data', () => {
            const series = [makeSeries({ key: 's1', data: [50, 200, 999] })]
            const scale = createYScale(series, dimensions, { percentStack: true })
            expect(scale.domain()[0]).toBe(0)
            // nice() may push domain slightly above 1 but never below 0
            expect(scale.domain()[1]).toBeGreaterThanOrEqual(1)
        })

        it('maps 0 to the bottom of the plot area', () => {
            const series = [makeSeries({ key: 's1', data: [1] })]
            const scale = createYScale(series, dimensions, { percentStack: true })
            expect(scale(0)).toBeCloseTo(dimensions.plotTop + dimensions.plotHeight, 0)
        })

        it('maps 1 to the top of the plot area', () => {
            const series = [makeSeries({ key: 's1', data: [1] })]
            const scale = createYScale(series, dimensions, { percentStack: true })
            expect(scale(1)).toBeCloseTo(dimensions.plotTop, 0)
        })
    })

    describe('createScales — single axis', () => {
        it('returns no yAxes map when all visible series share the default axis', () => {
            const series = [makeSeries({ key: 's1', data: [10] }), makeSeries({ key: 's2', data: [20] })]
            const result = createScales(series, ['a'], dimensions)
            expect(result.yAxes).toBeUndefined()
        })

        it('treats all-excluded series as single-axis (no yAxes map)', () => {
            const series = [
                makeSeries({ key: 'h1', data: [10], visibility: { excluded: true }, yAxisId: 'y1' }),
                makeSeries({ key: 'h2', data: [20], visibility: { excluded: true }, yAxisId: 'y2' }),
            ]
            const result = createScales(series, ['a'], dimensions)
            expect(result.yAxes).toBeUndefined()
        })
    })

    describe('createScales — multi-axis', () => {
        it('builds independent per-axis scales with their own domains', () => {
            const small = makeSeries({ key: 'small', data: [0, 1], yAxisId: DEFAULT_Y_AXIS_ID })
            const large = makeSeries({ key: 'large', data: [0, 1000], yAxisId: 'y1' })
            const result = createScales([small, large], ['a', 'b'], dimensions)
            expect(result.yAxes).not.toBeUndefined()
            const left = result.yAxes![DEFAULT_Y_AXIS_ID].scale
            const right = result.yAxes!.y1.scale
            // 50 is in the middle of left's [0, 1] domain → top of plot; and far below right's [0, 1000]
            // domain midpoint. Different scales → different pixels.
            expect(left(1)).not.toBeCloseTo(right(1), 0)
        })

        it.each([
            ['DEFAULT_Y_AXIS_ID first', [DEFAULT_Y_AXIS_ID, 'y1']],
            ['non-default first', ['y1', DEFAULT_Y_AXIS_ID]],
        ] as const)('assigns left to DEFAULT_Y_AXIS_ID regardless of series order (%s)', (_, [firstId, secondId]) => {
            const a = makeSeries({ key: 'a', data: [10], yAxisId: firstId })
            const b = makeSeries({ key: 'b', data: [20], yAxisId: secondId })
            const result = createScales([a, b], ['x'], dimensions)
            expect(result.yAxes![DEFAULT_Y_AXIS_ID].position).toBe('left')
            expect(result.yAxes!.y1.position).toBe('right')
        })

        it('points scales.y at the default axis for backward compat', () => {
            const a = makeSeries({ key: 'a', data: [0, 10], yAxisId: DEFAULT_Y_AXIS_ID })
            const b = makeSeries({ key: 'b', data: [0, 1000], yAxisId: 'y1' })
            const result = createScales([a, b], ['x', 'y'], dimensions)
            expect(result.y(10)).toBe(result.yAxes![DEFAULT_Y_AXIS_ID].scale(10))
        })

        it('falls back scales.y to the first axis when no series uses DEFAULT_Y_AXIS_ID', () => {
            const a = makeSeries({ key: 'a', data: [0, 10], yAxisId: 'y1' })
            const b = makeSeries({ key: 'b', data: [0, 1000], yAxisId: 'y2' })
            const result = createScales([a, b], ['x', 'y'], dimensions)
            // Without 'left', 'y1' takes the left position; scales.y should mirror it.
            expect(result.yAxes!.y1.position).toBe('left')
            expect(result.y(10)).toBe(result.yAxes!.y1.scale(10))
        })

        it('excludes visibility.excluded series from per-axis domain calculation', () => {
            const visible = makeSeries({ key: 'v', data: [0, 10], yAxisId: DEFAULT_Y_AXIS_ID })
            const hiddenOnLeft = makeSeries({
                key: 'h',
                data: [0, 9999],
                visibility: { excluded: true },
                yAxisId: DEFAULT_Y_AXIS_ID,
            })
            const otherAxis = makeSeries({ key: 'o', data: [0, 500], yAxisId: 'y1' })
            const result = createScales([visible, hiddenOnLeft, otherAxis], ['a', 'b'], dimensions)
            const [, leftMax] = result.yAxes![DEFAULT_Y_AXIS_ID].scale.domain() as [number, number]
            // nice() can extend the domain slightly but nowhere near 9999.
            expect(leftMax).toBeLessThan(100)
        })
    })

    describe('computePercentStackData', () => {
        it('returns an empty map when there are no series', () => {
            const result = computePercentStackData([], ['a', 'b'])
            expect(result.size).toBe(0)
        })

        it('returns an empty map when all series have visibility.excluded', () => {
            const series = [makeSeries({ key: 's1', data: [10, 20], visibility: { excluded: true } })]
            const result = computePercentStackData(series, ['a', 'b'])
            expect(result.size).toBe(0)
        })

        it('normalizes a single series so each top value equals 1.0', () => {
            const series = [makeSeries({ key: 's1', data: [10, 50, 200] })]
            const result = computePercentStackData(series, ['a', 'b', 'c'])
            const band = result.get('s1')!
            for (const v of band.top) {
                expect(v).toBeCloseTo(1, 5)
            }
            for (const v of band.bottom) {
                expect(v).toBeCloseTo(0, 5)
            }
        })

        it('produces top-of-stack values that sum to 1 across two series at each label', () => {
            const s1 = makeSeries({ key: 's1', data: [30, 70] })
            const s2 = makeSeries({ key: 's2', data: [70, 30] })
            const result = computePercentStackData([s1, s2], ['a', 'b'])
            const s2Band = result.get('s2')!
            for (const v of s2Band.top) {
                expect(v).toBeCloseTo(1, 5)
            }
        })

        it('excludes visibility.excluded series from the percent calculation', () => {
            const visible = makeSeries({ key: 'v', data: [50, 50] })
            const hidden = makeSeries({ key: 'h', data: [50, 50], visibility: { excluded: true } })
            const result = computePercentStackData([visible, hidden], ['a', 'b'])
            expect(result.has('h')).toBe(false)
            expect(result.has('v')).toBe(true)
            const band = result.get('v')!
            for (const v of band.top) {
                expect(v).toBeCloseTo(1, 5)
            }
        })

        it('clamps negative values to 0 before stacking', () => {
            const series = [makeSeries({ key: 's1', data: [-10, 50] }), makeSeries({ key: 's2', data: [50, 50] })]
            const result = computePercentStackData(series, ['a', 'b'])
            // at index 0, s1 is treated as 0 so s2 contributes 100%
            const s2 = result.get('s2')!
            expect(s2.top[0]).toBeCloseTo(1, 5)
        })

        it('handles all-zero data without throwing', () => {
            const series = [makeSeries({ key: 's1', data: [0, 0] })]
            expect(() => computePercentStackData(series, ['a', 'b'])).not.toThrow()
        })
    })

    describe('computeStackData', () => {
        it('returns an empty map when there are no series', () => {
            const result = computeStackData([], ['a', 'b'])
            expect(result.size).toBe(0)
        })

        it('returns an empty map when all series have visibility.excluded', () => {
            const series = [makeSeries({ key: 's1', data: [10, 20], visibility: { excluded: true } })]
            const result = computeStackData(series, ['a', 'b'])
            expect(result.size).toBe(0)
        })

        it('first series has bottom values of zero', () => {
            const series = [makeSeries({ key: 's1', data: [10, 20] })]
            const result = computeStackData(series, ['a', 'b'])
            const band = result.get('s1')!
            expect(band.top).toEqual([10, 20])
            expect(band.bottom).toEqual([0, 0])
        })

        it('stacks two series so second sits on top of first', () => {
            const s1 = makeSeries({ key: 's1', data: [10, 20] })
            const s2 = makeSeries({ key: 's2', data: [5, 15] })
            const result = computeStackData([s1, s2], ['a', 'b'])

            const band1 = result.get('s1')!
            expect(band1.top).toEqual([10, 20])
            expect(band1.bottom).toEqual([0, 0])

            const band2 = result.get('s2')!
            expect(band2.top).toEqual([15, 35])
            expect(band2.bottom).toEqual([10, 20])
        })

        it('stacks three series cumulatively', () => {
            const s1 = makeSeries({ key: 's1', data: [10] })
            const s2 = makeSeries({ key: 's2', data: [20] })
            const s3 = makeSeries({ key: 's3', data: [30] })
            const result = computeStackData([s1, s2, s3], ['a'])

            expect(result.get('s1')!.top).toEqual([10])
            expect(result.get('s2')!.top).toEqual([30])
            expect(result.get('s2')!.bottom).toEqual([10])
            expect(result.get('s3')!.top).toEqual([60])
            expect(result.get('s3')!.bottom).toEqual([30])
        })

        it('excludes visibility.excluded series from the stack', () => {
            const visible = makeSeries({ key: 'v', data: [10, 20] })
            const hidden = makeSeries({ key: 'h', data: [100, 200], visibility: { excluded: true } })
            const result = computeStackData([visible, hidden], ['a', 'b'])
            expect(result.has('h')).toBe(false)
            expect(result.get('v')!.top).toEqual([10, 20])
        })

        it('clamps negative values to 0', () => {
            const s1 = makeSeries({ key: 's1', data: [-10, 20] })
            const s2 = makeSeries({ key: 's2', data: [30, 10] })
            const result = computeStackData([s1, s2], ['a', 'b'])
            // s1 negative clamped to 0
            expect(result.get('s1')!.top).toEqual([0, 20])
            expect(result.get('s2')!.bottom).toEqual([0, 20])
            expect(result.get('s2')!.top).toEqual([30, 30])
        })

        it('stacks per yAxisId so series on different axes do not contaminate each others totals', () => {
            const left = makeSeries({ key: 'l', data: [10, 20], yAxisId: DEFAULT_Y_AXIS_ID })
            const right = makeSeries({ key: 'r', data: [1000, 2000], yAxisId: 'y1' })
            const result = computeStackData([left, right], ['a', 'b'])
            // Each axis stack starts from 0 — the right-axis values must not pile on top
            // of the left-axis values (and vice versa).
            expect(result.get('l')!.bottom).toEqual([0, 0])
            expect(result.get('l')!.top).toEqual([10, 20])
            expect(result.get('r')!.bottom).toEqual([0, 0])
            expect(result.get('r')!.top).toEqual([1000, 2000])
        })

        it('percent stack groups by yAxisId so each axis sums to 1 independently', () => {
            const l1 = makeSeries({ key: 'l1', data: [30, 70], yAxisId: DEFAULT_Y_AXIS_ID })
            const l2 = makeSeries({ key: 'l2', data: [70, 30], yAxisId: DEFAULT_Y_AXIS_ID })
            const r1 = makeSeries({ key: 'r1', data: [500, 500], yAxisId: 'y1' })
            const result = computePercentStackData([l1, l2, r1], ['a', 'b'])
            // Left axis: l2 sits on top of l1, sum = 1.
            for (const v of result.get('l2')!.top) {
                expect(v).toBeCloseTo(1, 5)
            }
            // Right axis: only one series, so its top is at 1.
            for (const v of result.get('r1')!.top) {
                expect(v).toBeCloseTo(1, 5)
            }
        })
    })

    describe('autoFormatYTick', () => {
        it.each([
            { domainMax: 0, value: 0.5, expected: '0.50', label: 'two decimal places when domainMax < 2' },
            { domainMax: 1, value: 0.123, expected: '0.12', label: 'two decimal places when domainMax equals 1' },
            { domainMax: 1.99, value: 1.5, expected: '1.50', label: 'two decimal places when domainMax is 1.99' },
            { domainMax: 2, value: 3.5, expected: '3.5', label: 'one decimal place when domainMax equals 2' },
            { domainMax: 4.99, value: 2.7, expected: '2.7', label: 'one decimal place when domainMax is 4.99' },
            { domainMax: 5, value: 42, expected: '42', label: 'no decimal places when domainMax equals 5' },
            { domainMax: 1000, value: 999, expected: '999', label: 'no decimal places when domainMax is large' },
            { domainMax: 10000, value: 1234, expected: '1,234', label: 'adds thousands separator' },
            {
                domainMax: 1000000,
                value: 123456,
                expected: '123,456',
                label: 'adds thousands separators for large values',
            },
        ])('returns $expected: $label', ({ domainMax, value, expected }) => {
            expect(autoFormatYTick(value, domainMax)).toBe(expected)
        })

        it('formats zero correctly when domainMax is large', () => {
            expect(autoFormatYTick(0, 100)).toBe('0')
        })

        it('formats negative values correctly', () => {
            expect(autoFormatYTick(-5, 10)).toBe('-5')
        })
    })
})
