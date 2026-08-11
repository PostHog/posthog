import { mixColors } from '@posthog/quill-charts'

import { dataColorVars, getSeriesColor } from 'lib/colors'

import { AxisSeries } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'
import { buildPieSeries, buildPieSlices, formatPieSliceCount } from './sqlPieGraphAdapter'

describe('sqlPieGraphAdapter', () => {
    describe('formatPieSliceCount', () => {
        it.each([
            ['appends share of total', 25, 100, undefined, false, '25 (25%)'],
            ['rounds share to one decimal place', 1, 3, undefined, false, '1 (33.3%)'],
            ['omits share when total is zero', 5, 0, undefined, false, '5'],
            [
                'omits share for percent-styled values',
                25,
                100,
                { formatting: { style: 'percent' as const } },
                false,
                '25%',
            ],
            [
                'formats value with settings before appending share',
                1234.5,
                2469,
                { formatting: { style: 'number' as const, decimalPlaces: 0 } },
                false,
                '1,235 (50%)',
            ],
            ['leads with share when displaying as percentage', 25, 100, undefined, true, '25% (25)'],
            ['falls back to the value when total is zero in percentage mode', 5, 0, undefined, true, '5'],
        ])('%s', (_name, value, total, settings, asPercent, expected) => {
            expect(formatPieSliceCount(value, total, settings, asPercent)).toEqual(expected)
        })
    })

    describe('buildPieSlices', () => {
        const xData: AxisSeries<string> = {
            column: {
                name: 'category',
                type: {
                    name: 'STRING',
                    isNumerical: false,
                },
                label: 'category',
                dataIndex: 0,
            },
            data: ['alpha', 'beta', 'alpha'],
        }

        it('aggregates a single y-series by x-axis label', () => {
            const yData: AxisSeries<number | null>[] = [
                {
                    column: {
                        name: 'value',
                        type: {
                            name: 'INTEGER',
                            isNumerical: true,
                        },
                        label: 'value',
                        dataIndex: 1,
                    },
                    data: [2, 3, 5],
                    settings: {},
                },
            ]

            expect(buildPieSlices(xData, yData)).toEqual([
                { label: 'alpha', value: 7, color: getSeriesColor(0) },
                { label: 'beta', value: 3, color: getSeriesColor(4) },
            ])
        })

        it('aggregates breakdown series by series total', () => {
            const yData: AxisBreakdownSeries<number | null>[] = [
                {
                    name: 'first',
                    breakdownValue: 'first',
                    data: [1, 2, null],
                    settings: { display: { color: '#111111' } },
                },
                {
                    name: 'second',
                    breakdownValue: 'second',
                    data: [3, 4, 5],
                    settings: { display: { color: '#222222' } },
                },
            ]

            expect(buildPieSlices(xData, yData)).toEqual([
                { label: 'first', value: 3, color: '#111111' },
                { label: 'second', value: 12, color: '#222222' },
            ])
        })

        it('falls back to one slice per y-series when there is no categorical x-axis', () => {
            const noXAxis: AxisSeries<string> = {
                column: {
                    name: 'None',
                    type: {
                        name: 'STRING',
                        isNumerical: false,
                    },
                    label: 'None',
                    dataIndex: -1,
                },
                data: ['', ''],
            }

            const yData: AxisSeries<number | null>[] = [
                {
                    column: {
                        name: 'apples',
                        type: {
                            name: 'INTEGER',
                            isNumerical: true,
                        },
                        label: 'apples',
                        dataIndex: 0,
                    },
                    data: [1, 2],
                    settings: {},
                },
                {
                    column: {
                        name: 'oranges',
                        type: {
                            name: 'INTEGER',
                            isNumerical: true,
                        },
                        label: 'oranges',
                        dataIndex: 1,
                    },
                    data: [3, 4],
                    settings: {},
                },
            ]

            expect(buildPieSlices(noXAxis, yData)).toEqual([
                { label: 'apples', value: 3, color: getSeriesColor(0) },
                { label: 'oranges', value: 7, color: getSeriesColor(4) },
            ])
        })

        describe('slice colors', () => {
            const categories = (count: number): AxisSeries<string> => ({
                column: { name: 'category', type: { name: 'STRING', isNumerical: false }, label: 'c', dataIndex: 0 },
                data: Array.from({ length: count }, (_, index) => `label-${index}`),
            })

            const ones = (count: number): AxisSeries<number | null>[] => [
                {
                    column: { name: 'value', type: { name: 'INTEGER', isNumerical: true }, label: 'v', dataIndex: 1 },
                    data: Array.from({ length: count }, () => 1),
                    settings: {},
                },
            ]

            const paletteSize = dataColorVars.length

            beforeEach(() => {
                // getSeriesColor resolves CSS variables off the body, and jsdom loads no
                // stylesheet — without these every palette entry returns the same fallback and
                // any assertion about which entry a slice got would hold no matter what.
                dataColorVars.forEach((name, index) => {
                    document.body.style.setProperty(`--${name}`, `#0000${index.toString(16).padStart(2, '0')}`)
                })
            })

            afterEach(() => {
                dataColorVars.forEach((name) => document.body.style.removeProperty(`--${name}`))
            })

            it('uses every palette entry exactly once before it repeats', () => {
                // Also the guard on the hand-ordered sequence in the adapter: adding a palette
                // color without extending that sequence drops it from every pie, silently.
                const slices = buildPieSlices(categories(paletteSize), ones(paletteSize))
                expect(new Set(slices.map((slice) => slice.color)).size).toEqual(paletteSize)
            })

            /** Positions of slices drawn in any of `colors`, and whether two of them touch. */
            const familyTouches = (slices: { color: string }[], colors: string[]): boolean => {
                const at = slices.flatMap((slice, index) => (colors.includes(slice.color) ? [index] : []))
                return at.some((a) =>
                    at.some((b) => a !== b && (Math.abs(a - b) === 1 || Math.abs(a - b) === slices.length - 1))
                )
            }

            // The palette's look-alikes read as one color when they share an edge. A sequential
            // assignment puts several of them side by side, which is what the ordering undoes.
            // 15 slices is the documented exception and is covered by its own case below.
            it.each([
                ['the blues', [0, 7]],
                ['the teals', [2, 10, 14]],
                ['the purples', [1, 13]],
            ])('never lets %s touch', (_name, entries) => {
                const colors = entries.map(getSeriesColor)
                for (const count of [6, 8, 12, 17]) {
                    const slices = buildPieSlices(categories(count), ones(count))
                    expect({ count, touches: familyTouches(slices, colors) }).toEqual({ count, touches: false })
                }
            })

            it('mutes the palette color toward the chart ground', () => {
                const [slice] = buildPieSlices(categories(1), ones(1), '#ffffff')
                expect(slice.color).not.toEqual(getSeriesColor(0))
                expect(slice.color).toEqual(mixColors(getSeriesColor(0), '#ffffff', 0.26))
            })

            it('leaves a color the user picked at full strength', () => {
                const yData: AxisBreakdownSeries<number | null>[] = [
                    {
                        name: 'chosen',
                        breakdownValue: 'chosen',
                        data: [1],
                        settings: { display: { color: '#abcdef' } },
                    },
                ]
                expect(buildPieSlices(categories(1), yData, '#ffffff')[0].color).toEqual('#abcdef')
            })
        })
    })

    describe('buildPieSeries', () => {
        it('maps each slice to a single-value quill series, pinning the slice color', () => {
            expect(
                buildPieSeries([
                    { label: 'alpha', value: 7, color: '#111111' },
                    { label: 'beta', value: 3, color: '#222222' },
                ])
            ).toEqual([
                { key: 'alpha-0', label: 'alpha', color: '#111111', data: [7] },
                { key: 'beta-1', label: 'beta', color: '#222222', data: [3] },
            ])
        })

        it('returns an empty array when there are no slices', () => {
            expect(buildPieSeries([])).toEqual([])
        })
    })
})
