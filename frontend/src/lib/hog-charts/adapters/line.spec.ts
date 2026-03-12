import type { ChartDataset } from 'chart.js'

import type { ComparisonSeries, DataPoint, LineProps, Series } from '../types'
import { buildAreaConfig, buildLineConfig } from './line'

jest.mock('lib/charts/utils/theme', () => ({
    buildTheme: jest.fn(() => ({
        colors: ['#1d4aff', '#e3a507', '#f46b00', '#0080ff', '#df7eff'],
        axisColor: '#999',
        gridColor: '#eee',
        crosshairColor: '#aaa',
        tooltipBackground: '#fff',
        tooltipColor: '#000',
    })),
    seriesColor: jest.fn((theme: { colors: string[] }, index: number) => theme.colors[index % theme.colors.length]),
}))

jest.mock('lib/charts/utils/format', () => ({
    formatValue: jest.fn((value: number) => String(value)),
}))

jest.mock('lib/charts/utils/dates', () => ({
    createXAxisTickCallback: jest.fn(() => jest.fn()),
}))

function dp(x: string | number, y: number, status?: 'incomplete'): DataPoint {
    return status ? { x, y, status } : { x, y }
}

function makeSeries(overrides?: Partial<Series> & { rawData?: number[] }): Series {
    const { rawData, ...rest } = overrides ?? {}
    return {
        label: 'Test Series',
        data: rawData ? rawData.map((v, i) => dp(String(i), v)) : [dp('Jan', 10), dp('Feb', 20), dp('Mar', 30)],
        ...rest,
    }
}

function makeProps(overrides?: Partial<LineProps>): LineProps {
    return {
        series: [makeSeries()],
        ...overrides,
    }
}

describe('hog-charts adapters/line', () => {
    describe('buildLineConfig', () => {
        describe('cumulative mode', () => {
            it('computes running sums when cumulative is true', () => {
                const config = buildLineConfig(
                    makeProps({
                        series: [makeSeries({ rawData: [1, 2, 3, 4] })],
                        options: { cumulative: true },
                    })
                )
                expect(config.data.datasets[0].data).toEqual([1, 3, 6, 10])
            })

            it('leaves data unchanged when cumulative is false', () => {
                const config = buildLineConfig(
                    makeProps({
                        series: [makeSeries({ rawData: [1, 2, 3] })],
                        options: { cumulative: false },
                    })
                )
                expect(config.data.datasets[0].data).toEqual([1, 2, 3])
            })
        })

        describe('stacked mode', () => {
            it('sets stacked flag on x and y axes', () => {
                const config = buildLineConfig(makeProps({ options: { stacked: true } }))
                const scales = (config.options as { scales: Record<string, { stacked?: boolean }> }).scales
                expect(scales.x.stacked).toBe(true)
                expect(scales.y.stacked).toBe(true)
            })

            it('does not set stacked flag when stacked is false', () => {
                const config = buildLineConfig(makeProps({ options: { stacked: false } }))
                const scales = (config.options as { scales: Record<string, { stacked?: unknown }> }).scales
                expect(scales.y.stacked).toBeUndefined()
            })
        })

        describe('percent stacked mode', () => {
            it('enables stacked100 plugin and stacked axes', () => {
                const config = buildLineConfig(makeProps({ options: { percentStacked: true } }))
                const plugins = (config.options as { plugins: Record<string, unknown> }).plugins
                expect(plugins.stacked100).toMatchObject({ enable: true })
                const scales = (config.options as { scales: Record<string, { stacked?: boolean }> }).scales
                expect(scales.y.stacked).toBe(true)
            })
        })

        describe('highlight series', () => {
            it('dims non-highlighted series with alpha suffixes', () => {
                const config = buildLineConfig(
                    makeProps({
                        series: [
                            makeSeries({ label: 'A', color: '#ff0000' }),
                            makeSeries({ label: 'B', color: '#00ff00' }),
                        ],
                        highlightSeriesIndex: 0,
                    })
                )
                expect(config.data.datasets[0].borderColor).toBe('#ff0000')
                expect(config.data.datasets[1].borderColor).toBe('#00ff0055')
                expect(config.data.datasets[1].backgroundColor).toBe('#00ff0033')
            })

            it('does not dim when highlightSeriesIndex is null', () => {
                const config = buildLineConfig(
                    makeProps({
                        series: [makeSeries({ color: '#ff0000' })],
                        highlightSeriesIndex: null,
                    })
                )
                expect(config.data.datasets[0].borderColor).toBe('#ff0000')
            })
        })

        describe('area mode', () => {
            it('encodes fillOpacity into backgroundColor hex suffix', () => {
                const config = buildLineConfig(
                    makeProps({
                        options: { isArea: true, fillOpacity: 0.5 },
                        series: [makeSeries({ color: '#ff0000' })],
                    })
                )
                expect(config.data.datasets[0].backgroundColor).toBe('#ff000080')
                expect(config.data.datasets[0].fill).toBe(true)
            })

            it('sets fill to "origin" when stacked', () => {
                const config = buildLineConfig(makeProps({ options: { isArea: true, stacked: true } }))
                expect(config.data.datasets[0].fill).toBe('origin')
            })

            it('sets fill to false when isArea is false and series has no fill override', () => {
                const config = buildLineConfig(makeProps({ options: { isArea: false } }))
                expect(config.data.datasets[0].fill).toBe(false)
            })

            it('respects per-series fill override', () => {
                const config = buildLineConfig(
                    makeProps({
                        options: { isArea: false, fillOpacity: 0.5 },
                        series: [makeSeries({ fill: true, color: '#ff0000' })],
                    })
                )
                expect(config.data.datasets[0].fill).toBe(true)
            })
        })

        describe('compare series', () => {
            const compareSeries: ComparisonSeries[] = [
                {
                    label: 'Series A',
                    compareLabel: 'last week',
                    data: [dp('Jan', 5), dp('Feb', 10), dp('Mar', 15)],
                    color: '#aabbcc',
                },
            ]

            it('appends with formatted label, dashed style, and reduced border width', () => {
                const config = buildLineConfig(makeProps({ compare: compareSeries, options: { lineWidth: 2 } }))
                expect(config.data.datasets).toHaveLength(2)
                expect(config.data.datasets[1].label).toBe('Series A (last week)')
                expect((config.data.datasets[1] as ChartDataset<'line'> & { borderDash: number[] }).borderDash).toEqual(
                    [6, 4]
                )
                expect(config.data.datasets[1].borderWidth).toBe(1.5)
            })
        })

        describe('incomplete data points', () => {
            it('produces segment config with borderDash for points with incomplete status', () => {
                const config = buildLineConfig(
                    makeProps({
                        series: [
                            makeSeries({
                                data: [
                                    dp('a', 1),
                                    dp('b', 2),
                                    dp('c', 3),
                                    dp('d', 4, 'incomplete'),
                                    dp('e', 5, 'incomplete'),
                                ],
                            }),
                        ],
                    })
                )
                const dataset = config.data.datasets[0] as ChartDataset<'line'> & {
                    segment?: { borderDash: (ctx: { p1DataIndex: number }) => number[] | undefined }
                }
                expect(dataset.segment).not.toBeUndefined()
                expect(dataset.segment!.borderDash({ p1DataIndex: 2 })).toBeUndefined()
                expect(dataset.segment!.borderDash({ p1DataIndex: 3 })).toEqual([10, 10])
            })

            it('does not produce segment config when no points are incomplete', () => {
                const config = buildLineConfig(makeProps())
                const dataset = config.data.datasets[0] as ChartDataset<'line'> & {
                    segment?: unknown
                }
                expect(dataset.segment).toBeUndefined()
            })
        })

        describe('maxSeries', () => {
            it('limits the number of datasets', () => {
                const config = buildLineConfig(
                    makeProps({
                        series: [makeSeries({ label: 'A' }), makeSeries({ label: 'B' }), makeSeries({ label: 'C' })],
                        options: { maxSeries: 2 },
                    })
                )
                expect(config.data.datasets).toHaveLength(2)
            })
        })

        describe('interpolation', () => {
            it('sets tension to 0.35 for smooth', () => {
                expect(
                    buildLineConfig(makeProps({ options: { interpolation: 'smooth' } })).data.datasets[0].tension
                ).toBe(0.35)
            })

            it('sets stepped to "before" for step', () => {
                expect(
                    buildLineConfig(makeProps({ options: { interpolation: 'step' } })).data.datasets[0].stepped
                ).toBe('before')
            })
        })

        describe('yAxisID assignment', () => {
            it('assigns "y1" when series yAxisPosition is "right"', () => {
                const config = buildLineConfig(makeProps({ series: [makeSeries({ yAxisPosition: 'right' })] }))
                expect((config.data.datasets[0] as ChartDataset<'line'> & { yAxisID: string }).yAxisID).toBe('y1')
            })
        })

        describe('hideXAxis / hideYAxis', () => {
            it('sets display to false on the respective axis', () => {
                const xConfig = buildLineConfig(makeProps({ options: { hideXAxis: true } }))
                const yConfig = buildLineConfig(makeProps({ options: { hideYAxis: true } }))
                const xScales = (xConfig.options as { scales: Record<string, { display: unknown }> }).scales
                const yScales = (yConfig.options as { scales: Record<string, { display: unknown }> }).scales
                expect(xScales.x.display).toBe(false)
                expect(yScales.y.display).toBe(false)
            })
        })

        describe('labels derived from data points', () => {
            it('derives labels from x-values of the first series', () => {
                const config = buildLineConfig(
                    makeProps({
                        series: [makeSeries({ data: [dp('Jan', 10), dp('Feb', 20), dp('Mar', 30)] })],
                    })
                )
                expect(config.data.labels).toEqual(['Jan', 'Feb', 'Mar'])
            })
        })

        describe('date auto-detection', () => {
            it('auto-detects ISO date strings and sets up tick formatting', () => {
                const { createXAxisTickCallback } = require('lib/charts/utils/dates')
                createXAxisTickCallback.mockClear()

                buildLineConfig(
                    makeProps({
                        series: [makeSeries({ data: [dp('2024-01-15', 10), dp('2024-01-16', 20)] })],
                    })
                )
                expect(createXAxisTickCallback).toHaveBeenCalledWith({
                    interval: 'day',
                    allDays: ['2024-01-15', '2024-01-16'],
                    timezone: 'UTC',
                })
            })

            it('does not auto-detect when x-values are not dates', () => {
                const { createXAxisTickCallback } = require('lib/charts/utils/dates')
                createXAxisTickCallback.mockClear()

                buildLineConfig(
                    makeProps({
                        series: [makeSeries({ data: [dp('Jan', 10), dp('Feb', 20)] })],
                    })
                )
                expect(createXAxisTickCallback).not.toHaveBeenCalled()
            })
        })
    })

    describe('buildAreaConfig', () => {
        it('enables fill with default fillOpacity of 0.1', () => {
            const config = buildAreaConfig({
                series: [makeSeries({ color: '#ff0000' })],
            })
            expect(config.data.datasets[0].fill).toBe(true)
            expect(config.data.datasets[0].backgroundColor).toBe('#ff00001a')
        })

        it('respects explicit fillOpacity override', () => {
            const config = buildAreaConfig({
                series: [makeSeries({ color: '#ff0000' })],
                options: { fillOpacity: 0.5 },
            })
            expect(config.data.datasets[0].backgroundColor).toBe('#ff000080')
        })
    })
})
