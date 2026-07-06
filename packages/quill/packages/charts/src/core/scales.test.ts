import { dimensions, makeSeries } from '../testing'
import {
    autoFormatYTick,
    buildSegmentResolveValue,
    buildStackedPositionValue,
    computeDivergingStackData,
    computePercentStackData,
    computeStackData,
    createBarScales,
    createScales,
    createXScale,
    createYScale,
    niceLogDomain,
    yTickCountForHeight,
} from './scales'
import type { StackedBand } from './scales'
import { DEFAULT_Y_AXIS_ID } from './types'

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

        it('floats the baseline to the data range when floatBaseline is set', () => {
            const series = [makeSeries({ key: 's1', data: [50, 60, 70] })]
            const [domainMin] = createYScale(series, dimensions, { floatBaseline: true }).domain()
            // Without floatBaseline this would clamp to 0; floated, the floor tracks the data minimum.
            expect(domainMin).toBeGreaterThan(0)
            expect(domainMin).toBeLessThanOrEqual(50)
        })

        it('ignores floatBaseline on a log scale (no zero baseline to drop)', () => {
            const series = [makeSeries({ key: 's1', data: [50, 60, 70] })]
            const [domainMin] = createYScale(series, dimensions, { floatBaseline: true, scaleType: 'log' }).domain()
            expect(domainMin).toBeGreaterThan(0)
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

        it('widens the domain to cover a confidence ribbon lower bound below the data', () => {
            // The ribbon top is the series data; fill.lowerData is the bottom of the band and
            // must influence the axis, otherwise the band clips at the series line.
            const band = makeSeries({ key: 'ci', data: [50, 60, 70], fill: { lowerData: [-20, -10, 30] } })
            const [domainMin] = createYScale([band], dimensions).domain()
            expect(domainMin).toBeLessThanOrEqual(-20)
        })

        it('lets a ribbon lower bound below 0 suppress the positive-data zero baseline clamp', () => {
            // Without folding lowerData in, all `data` are positive so min would clamp to 0.
            const band = makeSeries({ key: 'ci', data: [10, 20, 30], fill: { lowerData: [-5, -15, 5] } })
            const [domainMin] = createYScale([band], dimensions).domain()
            expect(domainMin).toBeLessThan(0)
        })

        it.each([
            {
                description: 'clips baseline to 0 when an overlay dips below 0 but primary data is non-negative',
                primaryData: [0, 0, 5000, 14500],
                overlayData: [-1000, 4000, 7000, 10000],
                expectedMin: 0,
                expectMaxAtLeast: undefined as number | undefined,
            },
            {
                description: 'preserves negative axis when primary data has genuine negatives',
                primaryData: [-50, 0, 100],
                overlayData: [-10, 50, 110],
                expectedMin: 'negative' as const,
                expectMaxAtLeast: undefined,
            },
            {
                description: 'lets overlay extend max even when baseline is clipped to 0',
                primaryData: [0, 50, 100],
                overlayData: [200, 250, 300],
                expectedMin: 0,
                expectMaxAtLeast: 300,
            },
        ])('$description', ({ primaryData, overlayData, expectedMin, expectMaxAtLeast }) => {
            const main = makeSeries({ key: 'main', data: primaryData })
            const trendline = makeSeries({ key: 'trend', data: overlayData, overlay: true })
            const [domainMin, domainMax] = createYScale([main, trendline], dimensions).domain()
            if (expectedMin === 'negative') {
                expect(domainMin).toBeLessThan(0)
            } else {
                expect(domainMin).toBe(expectedMin)
            }
            if (expectMaxAtLeast !== undefined) {
                expect(domainMax).toBeGreaterThanOrEqual(expectMaxAtLeast)
            }
        })

        it('maps the output range from plotTop + plotHeight down to plotTop', () => {
            const series = [makeSeries({ key: 's1', data: [0, 100] })]
            const scale = createYScale(series, dimensions)
            const [rangeMax, rangeMin] = scale.range()
            expect(rangeMax).toBe(dimensions.plotTop + dimensions.plotHeight)
            expect(rangeMin).toBe(dimensions.plotTop)
        })
    })

    describe('createYScale — valueDomain { include } (goal lines)', () => {
        it('extends the domain upward to include a goal line above the data', () => {
            const series = [makeSeries({ key: 's1', data: [10, 20, 30] })]
            const scale = createYScale(series, dimensions, { valueDomain: { include: [100] } })
            expect(scale.domain()[1]).toBeGreaterThanOrEqual(100)
            expect(scale.domain()[0]).toBe(0)
        })

        it('extends the domain downward to include a negative goal line on positive data', () => {
            const series = [makeSeries({ key: 's1', data: [10, 20, 30] })]
            const scale = createYScale(series, dimensions, { valueDomain: { include: [-50] } })
            expect(scale.domain()[0]).toBeLessThanOrEqual(-50)
        })

        it('still clips an overlay-driven negative baseline to 0 when include values are non-negative', () => {
            const main = makeSeries({ key: 'main', data: [0, 5000, 14500] })
            const trendline = makeSeries({ key: 'trend', data: [-1000, 7000, 10000], overlay: true })
            const scale = createYScale([main, trendline], dimensions, { valueDomain: { include: [20000] } })
            expect(scale.domain()[0]).toBe(0)
            expect(scale.domain()[1]).toBeGreaterThanOrEqual(20000)
        })

        it('leaves the data-derived domain unchanged when the goal line is within range', () => {
            const series = [makeSeries({ key: 's1', data: [0, 50, 100] })]
            const withGoal = createYScale(series, dimensions, { valueDomain: { include: [50] } })
            const withoutGoal = createYScale(series, dimensions)
            expect(withGoal.domain()).toEqual(withoutGoal.domain())
        })

        it('extends the log-scale domain to include a goal line above the data', () => {
            const series = [makeSeries({ key: 's1', data: [3, 50, 700] })]
            const scale = createYScale(series, dimensions, { scaleType: 'log', valueDomain: { include: [9000] } })
            expect(scale.domain()[1]).toBeGreaterThanOrEqual(9000)
        })

        it('is ignored under percent stack mode', () => {
            const series = [makeSeries({ key: 's1', data: [50, 100] })]
            const scale = createYScale(series, dimensions, { percentStack: true, valueDomain: { include: [500] } })
            expect(scale.domain()[0]).toBe(0)
            expect(scale.domain()[1]).toBeGreaterThanOrEqual(1)
            expect(scale.domain()[1]).toBeLessThan(2)
        })

        it.each([
            ['a positive goal anchors to zero', [100], 100],
            ['a zero goal still yields a unit span', [0], 0],
        ])('stays well-formed with no data and only %s', (_name, include, goal) => {
            const scale = createYScale([], dimensions, { valueDomain: { include } })
            const [lo, hi] = scale.domain()
            expect(lo).toBeLessThan(hi)
            expect(isFinite(scale(goal))).toBe(true)
        })
    })

    describe('createYScale — valueDomain [min, max] (fixed)', () => {
        it('pins the domain regardless of data and skips nice()', () => {
            const series = [makeSeries({ key: 's1', data: [10, 20, 30] })]
            const scale = createYScale(series, dimensions, { valueDomain: [0, 40] })
            expect(scale.domain()).toEqual([0, 40])
        })

        it('takes precedence over percent stack mode', () => {
            const series = [makeSeries({ key: 's1', data: [10, 20, 30] })]
            const scale = createYScale(series, dimensions, { percentStack: true, valueDomain: [0, 200] })
            expect(scale.domain()).toEqual([0, 200])
        })
    })

    describe('createYScale — log mode', () => {
        it('returns a log scale', () => {
            const series = [makeSeries({ key: 's1', data: [1, 10, 100] })]
            const scale = createYScale(series, dimensions, { scaleType: 'log' })
            expect('base' in scale).toBe(true)
        })

        it('uses one decade below smallest non-zero value as domain min', () => {
            const series = [makeSeries({ key: 's1', data: [0, 4, 21] })]
            const scale = createYScale(series, dimensions, { scaleType: 'log' })
            expect(scale.domain()[0]).toBe(1)
        })

        it('rounds domain max up to next nice multiple within its decade', () => {
            const series = [makeSeries({ key: 's1', data: [4, 21] })]
            const scale = createYScale(series, dimensions, { scaleType: 'log' })
            expect(scale.domain()[1]).toBe(30)
        })

        it('handles sub-unit data by picking a fractional domain min', () => {
            const series = [makeSeries({ key: 's1', data: [0.5, 8] })]
            const scale = createYScale(series, dimensions, { scaleType: 'log' })
            expect(scale.domain()[0]).toBeCloseTo(0.1, 10)
        })

        it('clamps zero values to the domain min via clamp(true)', () => {
            const series = [makeSeries({ key: 's1', data: [0, 4, 21] })]
            const scale = createYScale(series, dimensions, { scaleType: 'log' })
            const [domainMin] = scale.domain()
            expect(scale(0)).toBeCloseTo(scale(domainMin), 5)
        })

        it('maps higher values to lower pixel positions (top of chart)', () => {
            const series = [makeSeries({ key: 's1', data: [1, 100] })]
            const scale = createYScale(series, dimensions, { scaleType: 'log' })
            expect(scale(100)).toBeLessThan(scale(1))
        })

        it('falls back to a linear scale when no positive values exist', () => {
            const series = [makeSeries({ key: 's1', data: [-100, -50, -10] })]
            const scale = createYScale(series, dimensions, { scaleType: 'log' })
            const [domainMin, domainMax] = scale.domain()
            expect(domainMin).toBeLessThan(domainMax)
            expect(scale(-100)).not.toBeCloseTo(scale(-10), 0)
        })

        it('stays well-formed on all-zero data (degenerate linear fallback)', () => {
            // No positive values → linear fallback; min === max === 0 would collapse to a
            // [0, 0] domain mapping everything to NaN without the bracketing guard.
            const series = [makeSeries({ key: 's1', data: [0, 0, 0] })]
            const scale = createYScale(series, dimensions, { scaleType: 'log' })
            const [domainMin, domainMax] = scale.domain()
            expect(domainMin).toBeLessThan(domainMax)
            expect(isFinite(scale(0))).toBe(true)
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

        it('extends only the primary axis for goal lines, leaving secondary axes untouched', () => {
            const left = makeSeries({ key: 'left', data: [0, 10], yAxisId: DEFAULT_Y_AXIS_ID })
            const right = makeSeries({ key: 'right', data: [0, 500], yAxisId: 'y1' })
            const result = createScales([left, right], ['a', 'b'], dimensions, { valueDomain: { include: [1000] } })
            expect(result.yAxes![DEFAULT_Y_AXIS_ID].scale.domain()[1]).toBeGreaterThanOrEqual(1000)
            // The right axis is unaffected — nice() can nudge 500 up a little, but nowhere near 1000.
            expect(result.yAxes!.y1.scale.domain()[1]).toBeLessThan(1000)
        })

        it('applies a per-axis scaleType from options.axes to that axis only', () => {
            const left = makeSeries({ key: 'left', data: [1, 1000], yAxisId: DEFAULT_Y_AXIS_ID })
            const right = makeSeries({ key: 'right', data: [1, 1000], yAxisId: 'y1' })
            const result = createScales([left, right], ['a', 'b'], dimensions, {
                axes: [
                    { id: DEFAULT_Y_AXIS_ID, position: 'left', scaleType: 'linear' },
                    { id: 'y1', position: 'right', scaleType: 'log' },
                ],
            })
            // The log axis compresses the low end far more than the linear one for identical data.
            const linearMid = result.yAxes![DEFAULT_Y_AXIS_ID].scale(100)
            const logMid = result.yAxes!.y1.scale(100)
            expect(linearMid).not.toBeCloseTo(logMid, 0)
        })

        it('honors a config-driven position over the alternating default', () => {
            const a = makeSeries({ key: 'a', data: [0, 10], yAxisId: DEFAULT_Y_AXIS_ID })
            const b = makeSeries({ key: 'b', data: [0, 1000], yAxisId: 'y1' })
            // Both axes forced to the right side — the alternating default would put 'left' on the left.
            const result = createScales([a, b], ['x', 'y'], dimensions, {
                axes: [
                    { id: DEFAULT_Y_AXIS_ID, position: 'right' },
                    { id: 'y1', position: 'right' },
                ],
            })
            expect(result.yAxes![DEFAULT_Y_AXIS_ID].position).toBe('right')
            expect(result.yAxes!.y1.position).toBe('right')
        })

        it('builds a right-positioned yAxes record for a sole axis pinned right', () => {
            // A single series whose only axis is configured `position: 'right'` — the alternating
            // default would place index 0 on the left, so without honoring the override the gutter
            // renders left. The scalar fast path would also drop the yAxes record entirely.
            const only = makeSeries({ key: 'only', data: [0, 1200], yAxisId: 'right' })
            const result = createScales([only], ['a', 'b'], dimensions, {
                axes: [
                    { id: DEFAULT_Y_AXIS_ID, position: 'left' },
                    { id: 'right', position: 'right' },
                ],
            })
            expect(result.yAxes).not.toBeUndefined()
            expect(result.yAxes!.right.position).toBe('right')
            // scales.y mirrors the sole axis so gridlines align with the right gutter's ticks.
            expect(result.y(600)).toBe(result.yAxes!.right.scale(600))
        })

        it('uses a single-axis options.axes scaleType for the sole axis', () => {
            const only = makeSeries({ key: 'only', data: [1, 10, 100, 1000] })
            const result = createScales([only], ['a', 'b', 'c', 'd'], dimensions, {
                axes: [{ id: DEFAULT_Y_AXIS_ID, position: 'left', scaleType: 'log' }],
            })
            // Single axis → no yAxes map, but the sole scale picks up the log scaleType.
            expect(result.yAxes).toBeUndefined()
            const [min] = result.y.domain() as [number, number]
            expect(min).toBeGreaterThan(0)
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

        it.each(['s1', 's2'])('replaces NaN with 0 for series %s in an all-zero column', (key) => {
            const s1 = makeSeries({ key: 's1', data: [10, 0, 30] })
            const s2 = makeSeries({ key: 's2', data: [20, 0, 40] })
            const result = computePercentStackData([s1, s2], ['a', 'b', 'c'])
            const band = result.get(key)!
            expect(band.top.every(Number.isFinite)).toBe(true)
            expect(band.bottom.every(Number.isFinite)).toBe(true)
            expect(band.top[1]).toBe(0)
            expect(band.bottom[1]).toBe(0)
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

        it('computeDivergingStackData preserves negative values, stacking them below 0', () => {
            const positive = makeSeries({ key: 'pos', data: [10, 20] })
            const negative = makeSeries({ key: 'neg', data: [-5, -7] })
            const result = computeDivergingStackData([positive, negative], ['a', 'b'])
            // Positive stacks above zero, negative stacks below zero — diverging offset
            // keeps both signs intact instead of clamping the negative to 0.
            expect(result.get('pos')!.bottom).toEqual([0, 0])
            expect(result.get('pos')!.top).toEqual([10, 20])
            expect(result.get('neg')!.bottom).toEqual([-5, -7])
            expect(result.get('neg')!.top).toEqual([0, 0])
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

    describe('yTickCountForHeight', () => {
        it.each([
            { plotHeight: 0, expected: 2 },
            { plotHeight: 50, expected: 2 },
            { plotHeight: 100, expected: 2 },
            { plotHeight: 200, expected: 4 },
            { plotHeight: 400, expected: 8 },
            { plotHeight: 550, expected: 11 },
            { plotHeight: 1600, expected: 11 },
        ])('plotHeight $plotHeight → $expected ticks', ({ plotHeight, expected }) => {
            expect(yTickCountForHeight(plotHeight)).toBe(expected)
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

    describe('niceLogDomain', () => {
        it.each([
            { minPositive: 740, max: 4200, expected: [100, 5000] },
            { minPositive: 1, max: 100, expected: [0.1, 100] },
            { minPositive: 0.5, max: 9, expected: [0.1, 9] },
            { minPositive: 25, max: 25, expected: [10, 30] },
            { minPositive: 1000, max: 9999, expected: [100, 10000] },
        ])('rounds [$minPositive, $max] to $expected', ({ minPositive, max, expected }) => {
            const [niceMin, niceMax] = niceLogDomain(minPositive, max)
            expect(niceMin).toBeCloseTo(expected[0], 5)
            expect(niceMax).toBeCloseTo(expected[1], 5)
        })

        it('always rounds minPositive down past it (next decade lower)', () => {
            const [niceMin] = niceLogDomain(50, 1000)
            expect(niceMin).toBeLessThanOrEqual(50)
        })
    })

    describe('buildStackedPositionValue', () => {
        const series = makeSeries({ key: 'a', data: [10, 20, 30] })

        it('returns undefined when stackedData is undefined', () => {
            expect(buildStackedPositionValue(undefined)).toBeUndefined()
        })

        it('returns the stacked top when present and finite', () => {
            const stacked = new Map<string, StackedBand>([['a', { top: [100, 200, 300], bottom: [0, 0, 0] }]])
            const resolve = buildStackedPositionValue(stacked)!
            expect(resolve(series, 0)).toBe(100)
            expect(resolve(series, 2)).toBe(300)
        })

        it('falls back to the raw value when the series is not in the stack', () => {
            const stacked = new Map<string, StackedBand>()
            const resolve = buildStackedPositionValue(stacked)!
            expect(resolve(series, 1)).toBe(20)
        })

        it('falls back to the raw value when the stacked top is non-finite', () => {
            const stacked = new Map<string, StackedBand>([['a', { top: [NaN, Infinity, 50], bottom: [0, 0, 0] }]])
            const resolve = buildStackedPositionValue(stacked)!
            expect(resolve(series, 0)).toBe(10)
            expect(resolve(series, 1)).toBe(20)
            expect(resolve(series, 2)).toBe(50)
        })

        it('returns 0 when both stacked top and raw value are non-finite', () => {
            const nanSeries = makeSeries({ key: 'a', data: [NaN, Infinity, 0] })
            const stacked = new Map<string, StackedBand>([['a', { top: [NaN, NaN, 0], bottom: [0, 0, 0] }]])
            const resolve = buildStackedPositionValue(stacked)!
            expect(resolve(nanSeries, 0)).toBe(0)
            expect(resolve(nanSeries, 1)).toBe(0)
        })
    })

    describe('buildSegmentResolveValue', () => {
        const series = makeSeries({ key: 'a', data: [10, 20, 30] })

        it('returns undefined when stackedData is undefined', () => {
            expect(buildSegmentResolveValue(undefined)).toBeUndefined()
        })

        it('returns the segment height (top − bottom), not the cumulative top', () => {
            // `a` sits on top of 490 of other series, so its top is 980 but its own value is 490.
            const stacked = new Map<string, StackedBand>([['a', { top: [490, 980, 1470], bottom: [0, 490, 980] }]])
            const resolve = buildSegmentResolveValue(stacked)!
            expect(resolve(series, 0)).toBe(490)
            expect(resolve(series, 1)).toBe(490)
            expect(resolve(series, 2)).toBe(490)
        })

        it('falls back to the raw value when the series is not in the stack', () => {
            const resolve = buildSegmentResolveValue(new Map<string, StackedBand>())!
            expect(resolve(series, 1)).toBe(20)
        })

        it('falls back to the raw value when either the segment top or bottom is non-finite', () => {
            // The guard requires both top and bottom finite, so a NaN on either edge falls back to raw.
            const stacked = new Map<string, StackedBand>([['a', { top: [NaN, 20, 980], bottom: [0, NaN, 490] }]])
            const resolve = buildSegmentResolveValue(stacked)!
            expect(resolve(series, 0)).toBe(10) // top NaN → raw 10
            expect(resolve(series, 1)).toBe(20) // bottom NaN → raw 20
            expect(resolve(series, 2)).toBe(490) // both finite → 980 - 490
        })

        it('returns 0 when both the segment and the raw value are non-finite', () => {
            const nanSeries = makeSeries({ key: 'a', data: [NaN, Infinity, 0] })
            const stacked = new Map<string, StackedBand>([['a', { top: [NaN, 10, 0], bottom: [NaN, NaN, 0] }]])
            const resolve = buildSegmentResolveValue(stacked)!
            expect(resolve(nanSeries, 0)).toBe(0) // segment NaN + raw NaN → 0
            expect(resolve(nanSeries, 1)).toBe(0) // bottom NaN + raw Infinity → 0
        })

        it('resolves a negative-valued count-stacked series to 0 (buildStackData floors it)', () => {
            // buildStackData clamps data to >= 0 before stacking, so a negative series has a
            // zero-height segment — the resolver reports 0, not the raw negative value.
            const negSeries = makeSeries({ key: 'a', data: [10, -50] })
            const resolve = buildSegmentResolveValue(computeStackData([negSeries], ['x', 'y']))!
            expect(resolve(negSeries, 0)).toBe(10)
            expect(resolve(negSeries, 1)).toBe(0)
        })

        it('returns each series own fraction for a percent stack, not the cumulative fraction', () => {
            // a=20, b=15 at index 1 → total 35. b sits on top of a, so b's cumulative top is 1.0,
            // but its own fraction is 15/35 — that segment is what the tooltip must report.
            const a = makeSeries({ key: 'a', data: [10, 20] })
            const b = makeSeries({ key: 'b', data: [5, 15] })
            const resolve = buildSegmentResolveValue(computePercentStackData([a, b], ['x', 'y']))!
            expect(resolve(a, 1)).toBeCloseTo(20 / 35, 5)
            expect(resolve(b, 1)).toBeCloseTo(15 / 35, 5)
        })
    })

    describe('createBarScales — horizontal fitToHeight', () => {
        // plotHeight 100 / minBandSize 24 => 4 rows fit.
        const shortDims = { ...dimensions, plotTop: 0, plotHeight: 100 }
        const labels = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j']
        const series = [makeSeries({ key: 's', data: labels.map((_, i) => 10 - i) })]

        it('caps the band domain to the rows that fit at minBandSize, keeping the leading rows', () => {
            const { band } = createBarScales(series, labels, shortDims, {
                axisOrientation: 'horizontal',
                fitToHeight: true,
                minBandSize: 24,
            })
            expect(band.domain()).toEqual(['a', 'b', 'c', 'd'])
            expect(band.bandwidth()).toBeGreaterThanOrEqual(20)
        })

        it('keeps every row when they all fit', () => {
            const { band } = createBarScales(
                series.map((s) => ({ ...s, data: [1, 2, 3] })),
                ['a', 'b', 'c'],
                shortDims,
                {
                    axisOrientation: 'horizontal',
                    fitToHeight: true,
                    minBandSize: 24,
                }
            )
            expect(band.domain()).toEqual(['a', 'b', 'c'])
        })

        it('does not cap when fitToHeight is off (grow-to-fit-all behavior)', () => {
            const { band } = createBarScales(series, labels, shortDims, {
                axisOrientation: 'horizontal',
                minBandSize: 24,
            })
            expect(band.domain()).toEqual(labels)
        })

        it('ignores fitToHeight for vertical charts', () => {
            const { band } = createBarScales(series, labels, shortDims, {
                axisOrientation: 'vertical',
                fitToHeight: true,
                minBandSize: 24,
            })
            expect(band.domain()).toEqual(labels)
        })
    })
})
