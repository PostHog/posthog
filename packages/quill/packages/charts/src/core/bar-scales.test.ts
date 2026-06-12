import { dimensions, makeSeries } from '../testing'
import { createBarScales, groupedBandSlot } from './scales'

describe('hog-charts bar scales', () => {
    describe('createBarScales — vertical orientation (default)', () => {
        it.each([
            {
                orientation: 'vertical' as const,
                rangeStart: dimensions.plotLeft,
                rangeEnd: dimensions.plotLeft + dimensions.plotWidth,
            },
            {
                orientation: 'horizontal' as const,
                rangeStart: dimensions.plotTop,
                rangeEnd: dimensions.plotTop + dimensions.plotHeight,
            },
        ])('places bands across the categorical axis ($orientation)', ({ orientation, rangeStart, rangeEnd }) => {
            const series = [makeSeries({ key: 's1', data: [10, 20, 30] })]
            const { band } = createBarScales(series, ['a', 'b', 'c'], dimensions, { axisOrientation: orientation })
            const bandStart = band('a')!
            expect(bandStart).toBeGreaterThanOrEqual(rangeStart)
            expect(bandStart + band.bandwidth()).toBeLessThanOrEqual(rangeEnd + 1)
        })

        it('produces a bandwidth proportional to the number of labels', () => {
            const series = [makeSeries({ key: 's1', data: [1, 2, 3, 4] })]
            const four = createBarScales(series, ['a', 'b', 'c', 'd'], dimensions)
            const two = createBarScales(series, ['a', 'b'], dimensions)
            expect(four.band.bandwidth()).toBeLessThan(two.band.bandwidth())
        })

        it('inverts the value scale so larger values map to smaller y pixels', () => {
            const series = [makeSeries({ key: 's1', data: [0, 50, 100] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions)
            expect(value(100)).toBeLessThan(value(0))
        })

        // Both signs must extend the value domain to include zero so bar baselines align with
        // the plot edge. expectedSign tracks whether the extreme pixel sits above (-1) or below
        // (+1) the zero pixel.
        it.each([
            { sign: 'positive', data: [40, 60, 80], extreme: 80, expectedSign: -1 },
            { sign: 'negative', data: [-40, -60, -80], extreme: -80, expectedSign: 1 },
        ])('extends the value domain to include zero ($sign data)', ({ data, extreme, expectedSign }) => {
            const series = [makeSeries({ key: 's1', data })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions)
            const yAtZero = value(0)
            expect(yAtZero).toBeGreaterThanOrEqual(dimensions.plotTop - 1)
            expect(yAtZero).toBeLessThanOrEqual(dimensions.plotTop + dimensions.plotHeight + 1)
            expect(Math.sign(value(extreme) - yAtZero)).toBe(expectedSign)
        })

        it('returns a group scale only for grouped layout', () => {
            const series = [makeSeries({ key: 's1', data: [1, 2] }), makeSeries({ key: 's2', data: [3, 4] })]
            const stacked = createBarScales(series, ['a', 'b'], dimensions, { barLayout: 'stacked' })
            const grouped = createBarScales(series, ['a', 'b'], dimensions, { barLayout: 'grouped' })
            expect(stacked.group).toBeUndefined()
            expect(grouped.group).not.toBeUndefined()
            expect(grouped.group!.bandwidth()).toBeLessThan(grouped.band.bandwidth())
        })

        it('uses [0, 1] for the value domain in percent layout', () => {
            const series = [makeSeries({ key: 's1', data: [50, 100, 150] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions, { barLayout: 'percent' })
            const yAt1 = value(1)
            const yAt0 = value(0)
            expect(yAt1).toBeLessThan(yAt0)
            expect(value.domain()[0]).toBeCloseTo(0)
            expect(value.domain()[1]).toBeCloseTo(1)
        })
    })

    describe('createBarScales — pixel positioning', () => {
        it.each([
            { orientation: 'vertical' as const, expectedSign: -1 },
            { orientation: 'horizontal' as const, expectedSign: 1 },
        ])('places value(50) on the right side of value(0) for $orientation', ({ orientation, expectedSign }) => {
            const series = [makeSeries({ key: 's1', data: [0, 50] })]
            const { value } = createBarScales(series, ['a', 'b'], dimensions, { axisOrientation: orientation })
            expect(Math.sign(value(50) - value(0))).toBe(expectedSign)
        })

        it('makes consecutive band starts equally spaced', () => {
            const series = [makeSeries({ key: 's1', data: [1, 2, 3, 4] })]
            const { band } = createBarScales(series, ['a', 'b', 'c', 'd'], dimensions)
            const a = band('a')!
            const b = band('b')!
            const c = band('c')!
            expect(b - a).toBeCloseTo(c - b, 5)
        })

        it('group bandwidth times series count plus padding does not exceed band bandwidth', () => {
            const seriesArr = [
                makeSeries({ key: 's1', data: [1] }),
                makeSeries({ key: 's2', data: [2] }),
                makeSeries({ key: 's3', data: [3] }),
            ]
            const grouped = createBarScales(seriesArr, ['a'], dimensions, { barLayout: 'grouped' })
            const totalGroupSpan = grouped.group!.bandwidth() * 3
            expect(totalGroupSpan).toBeLessThanOrEqual(grouped.band.bandwidth())
        })
    })

    describe('createBarScales — empty / edge inputs', () => {
        it('returns a [0, 1] value domain when no series are provided', () => {
            const { value } = createBarScales([], ['a', 'b'], dimensions)
            expect(value.domain()).toEqual([0, 1])
        })

        it('uses stackedSeries values for the value domain when provided', () => {
            const rawSeries = [makeSeries({ key: 's1', data: [10] }), makeSeries({ key: 's2', data: [20] })]
            const stackedSeries = [makeSeries({ key: 's1', data: [10] }), makeSeries({ key: 's2', data: [30] })]
            const { value } = createBarScales(rawSeries, ['a'], dimensions, {
                barLayout: 'stacked',
                stackedSeries,
            })
            const yAtStackTop = value(30)
            expect(yAtStackTop).toBeGreaterThanOrEqual(dimensions.plotTop - 1)
            expect(yAtStackTop).toBeLessThanOrEqual(dimensions.plotTop + dimensions.plotHeight + 1)
        })

        it('skips excluded series when building the grouped sub-band', () => {
            const visible = makeSeries({ key: 'visible', data: [10] })
            const excluded = makeSeries({ key: 'excluded', data: [10], visibility: { excluded: true } })
            const { group } = createBarScales([visible, excluded], ['a'], dimensions, { barLayout: 'grouped' })
            expect(group?.('visible')).not.toBeUndefined()
            expect(group?.('excluded')).toBeUndefined()
        })
    })

    describe('createBarScales — valueDomain { include } (goal lines)', () => {
        it('extends the value domain upward to include a goal line above the data', () => {
            const series = [makeSeries({ key: 's1', data: [10, 20, 30] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions, { valueDomain: { include: [100] } })
            expect(value.domain()[1]).toBeGreaterThanOrEqual(100)
            const yAtGoal = value(100)
            expect(yAtGoal).toBeGreaterThanOrEqual(dimensions.plotTop - 1)
            expect(yAtGoal).toBeLessThanOrEqual(dimensions.plotTop + dimensions.plotHeight + 1)
        })

        it('extends the value domain downward to include a negative goal line', () => {
            const series = [makeSeries({ key: 's1', data: [10, 20, 30] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions, { valueDomain: { include: [-50] } })
            expect(value.domain()[0]).toBeLessThanOrEqual(-50)
        })

        it('leaves the data-derived domain unchanged when the goal line is within range', () => {
            const series = [makeSeries({ key: 's1', data: [0, 50, 100] })]
            const withGoal = createBarScales(series, ['a', 'b', 'c'], dimensions, { valueDomain: { include: [50] } })
            const withoutGoal = createBarScales(series, ['a', 'b', 'c'], dimensions)
            expect(withGoal.value.domain()).toEqual(withoutGoal.value.domain())
        })

        it('extends the log-scale domain to include a goal line above the data', () => {
            const series = [makeSeries({ key: 's1', data: [3, 50, 700] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions, {
                scaleType: 'log',
                valueDomain: { include: [9000] },
            })
            expect(value.domain()[1]).toBeGreaterThanOrEqual(9000)
        })

        it('is ignored under percent layout (domain stays [0, 1])', () => {
            const series = [makeSeries({ key: 's1', data: [10, 20, 30] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions, {
                barLayout: 'percent',
                valueDomain: { include: [500] },
            })
            expect(value.domain()[0]).toBeCloseTo(0)
            expect(value.domain()[1]).toBeCloseTo(1)
        })

        it.each([[100], [0], [-5]])('stays well-formed and zero-anchored with no data and only goal %s', (goal) => {
            const { value } = createBarScales([], ['a', 'b'], dimensions, { valueDomain: { include: [goal] } })
            const [lo, hi] = value.domain()
            expect(lo).toBeLessThan(hi)
            // The bar value axis always keeps a zero baseline, so the domain spans across 0.
            expect(lo).toBeLessThanOrEqual(0)
            expect(hi).toBeGreaterThanOrEqual(0)
            expect(isFinite(value(goal))).toBe(true)
        })
    })

    describe('createBarScales — valuePadding (headroom past the bars)', () => {
        const plotBottom = dimensions.plotTop + dimensions.plotHeight
        const plotRight = dimensions.plotLeft + dimensions.plotWidth

        it('holds back the requested px at the value-axis data end (vertical), baseline pinned', () => {
            const series = [makeSeries({ key: 's1', data: [0, 50, 100] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions, { valuePadding: 40 })
            // nice([0,100]) stays [0,100], so the data max lands exactly `padding` px below the top edge.
            expect(value(100)).toBeCloseTo(dimensions.plotTop + 40)
            expect(value(0)).toBeCloseTo(plotBottom)
        })

        it('holds back the requested px at the value-axis data end (horizontal)', () => {
            const series = [makeSeries({ key: 's1', data: [0, 50, 100] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions, {
                axisOrientation: 'horizontal',
                valuePadding: 60,
            })
            expect(value(100)).toBeCloseTo(plotRight - 60)
            expect(value(0)).toBeCloseTo(dimensions.plotLeft)
        })

        it('reserves at the negative extent end for all-negative data', () => {
            const series = [makeSeries({ key: 's1', data: [-50, -100] })]
            const { value } = createBarScales(series, ['a', 'b'], dimensions, { valuePadding: 40 })
            // Bars grow down to -100, which lands `padding` px above the bottom edge; zero stays at top.
            expect(value(-100)).toBeCloseTo(plotBottom - 40)
            expect(value(0)).toBeCloseTo(dimensions.plotTop)
        })

        it('leaves the axis untouched when padding is 0 / omitted', () => {
            const series = [makeSeries({ key: 's1', data: [0, 50, 100] })]
            const withPadding = createBarScales(series, ['a', 'b', 'c'], dimensions, { valuePadding: 0 })
            const without = createBarScales(series, ['a', 'b', 'c'], dimensions)
            expect(withPadding.value(100)).toBeCloseTo(without.value(100))
        })

        it('caps the reserve at a third of the axis so it never swallows the plot', () => {
            const series = [makeSeries({ key: 's1', data: [0, 100] })]
            const { value } = createBarScales(series, ['a', 'b'], dimensions, { valuePadding: 100_000 })
            expect(value(100)).toBeCloseTo(dimensions.plotTop + dimensions.plotHeight / 3)
        })
    })

    describe('createBarScales — valueDomain [min, max] (fixed)', () => {
        it.each([
            ['pins the domain regardless of data and skips nice()', undefined, [0, 40] as [number, number]],
            ['takes precedence over percent layout', 'percent' as const, [0, 200] as [number, number]],
        ])('%s', (_name, barLayout, valueDomain) => {
            const series = [makeSeries({ key: 's1', data: [10, 20, 30] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions, { barLayout, valueDomain })
            expect(value.domain()).toEqual(valueDomain)
        })
    })

    describe('createBarScales — log scale', () => {
        it('snaps the domain to enclosing decade boundaries with positive data', () => {
            const series = [makeSeries({ key: 's1', data: [3, 50, 700] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions, { scaleType: 'log' })
            const [lo, hi] = value.domain()
            expect(lo).toBeLessThanOrEqual(3)
            expect(hi).toBeGreaterThanOrEqual(700)
            expect(value(700)).toBeLessThan(value(3))
        })

        it('falls back to linear when the data has no positive values', () => {
            const series = [makeSeries({ key: 's1', data: [-10, -5, 0] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions, { scaleType: 'log' })
            const domain = value.domain()
            expect(domain[0]).toBeLessThanOrEqual(-10)
            expect(domain[1]).toBeGreaterThanOrEqual(0)
        })
    })

    describe('createBarScales — fitToHeight value domain', () => {
        // minBandSize == plotHeight forces maxBands = 1, so only the leading row survives.
        const dropToFirst = {
            axisOrientation: 'horizontal' as const,
            fitToHeight: true,
            minBandSize: dimensions.plotHeight,
        }

        it('scales the value axis to only the rows fitToHeight keeps', () => {
            const series = [makeSeries({ key: 's1', data: [5, 10, 999] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions, dropToFirst)
            // 999 sits in a dropped row, so it must not stretch the domain past the kept value.
            expect(value.domain()[1]).toBeLessThan(999)
        })

        it('keeps a large value in the domain when its row survives', () => {
            const series = [makeSeries({ key: 's1', data: [999, 5, 10] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions, dropToFirst)
            expect(value.domain()[1]).toBeGreaterThanOrEqual(999)
        })

        it('leaves the domain spanning every row when no rows are dropped', () => {
            const series = [makeSeries({ key: 's1', data: [5, 10, 999] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions, { axisOrientation: 'horizontal' })
            expect(value.domain()[1]).toBeGreaterThanOrEqual(999)
        })
    })

    describe('groupedBandSlot', () => {
        const series = [makeSeries({ key: 's1', data: [1, 2] }), makeSeries({ key: 's2', data: [3, 4] })]
        const grouped = createBarScales(series, ['a', 'b'], dimensions, { barLayout: 'grouped' })

        it("returns the series' band-axis slot within the band", () => {
            const start = grouped.band('a')!
            expect(groupedBandSlot(grouped, 'a', 's2')).toEqual({
                x: start + grouped.group!('s2')!,
                width: grouped.group!.bandwidth(),
            })
        })

        it('returns undefined for a series not in the group scale', () => {
            expect(groupedBandSlot(grouped, 'a', 'missing')).toBeUndefined()
        })

        it('returns undefined for non-grouped layouts (no group scale)', () => {
            const stacked = createBarScales(series, ['a', 'b'], dimensions, { barLayout: 'stacked' })
            expect(groupedBandSlot(stacked, 'a', 's1')).toBeUndefined()
        })
    })

    describe('createBarScales — multiple y-axes (grouped)', () => {
        const smallSeries = makeSeries({ key: 's1', data: [10, 20, 30] })
        const largeSeries = makeSeries({ key: 's2', data: [1000, 2000, 3000], yAxisId: 'y1' })

        it('builds a per-axis scale for each axis id, with the default axis on the left', () => {
            const { yAxes } = createBarScales([smallSeries, largeSeries], ['a', 'b', 'c'], dimensions, {
                barLayout: 'grouped',
            })
            expect(yAxes).not.toBeUndefined()
            expect(Object.keys(yAxes!).sort()).toEqual(['left', 'y1'])
            expect(yAxes!.left.position).toBe('left')
            expect(yAxes!.y1.position).toBe('right')
        })

        it('alternates sides for three axes (left, right, left)', () => {
            const third = makeSeries({ key: 's3', data: [50000, 60000, 70000], yAxisId: 'y2' })
            const { yAxes } = createBarScales([smallSeries, largeSeries, third], ['a', 'b', 'c'], dimensions, {
                barLayout: 'grouped',
            })
            expect(yAxes!.left.position).toBe('left')
            expect(yAxes!.y1.position).toBe('right')
            expect(yAxes!.y2.position).toBe('left')
        })

        it('scales each series against its own domain so both fill the plot height', () => {
            const { value, yAxes } = createBarScales([smallSeries, largeSeries], ['a', 'b', 'c'], dimensions, {
                barLayout: 'grouped',
            })
            // The small series' max (30) and the large series' max (3000) both map near the plot top
            // because each axis covers only its own series' range.
            expect(yAxes!.left.scale(30)).toBeCloseTo(yAxes!.y1.scale(3000), 0)
            // `value` is the primary (left) axis scale.
            expect(value(30)).toBeCloseTo(yAxes!.left.scale(30), 5)
        })

        it('keeps a single shared scale when only one axis id is present', () => {
            const { yAxes } = createBarScales(
                [smallSeries, makeSeries({ key: 's2', data: [40, 50, 60] })],
                ['a', 'b', 'c'],
                dimensions,
                { barLayout: 'grouped' }
            )
            expect(yAxes).toBeUndefined()
        })

        it('ignores per-series axes for stacked layouts (shared axis only)', () => {
            const { yAxes } = createBarScales([smallSeries, largeSeries], ['a', 'b', 'c'], dimensions, {
                barLayout: 'stacked',
            })
            expect(yAxes).toBeUndefined()
        })
    })
})
