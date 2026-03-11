import type { ChartDataset } from 'chart.js'

import type { ComparisonSeries, LineProps, Series } from '../types'
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

function makeSeries(overrides?: Partial<Series>): Series {
    return {
        label: 'Test Series',
        data: [10, 20, 30],
        ...overrides,
    }
}

function makeProps(overrides?: Partial<LineProps>): LineProps {
    return {
        data: [makeSeries()],
        labels: ['Jan', 'Feb', 'Mar'],
        ...overrides,
    }
}

describe('hog-charts adapters/line', () => {
    describe('buildLineConfig', () => {
        describe('cumulative mode', () => {
            it('computes running sums when cumulative is true', () => {
                const config = buildLineConfig(
                    makeProps({
                        data: [makeSeries({ data: [1, 2, 3, 4] })],
                        cumulative: true,
                    })
                )
                expect(config.data.datasets[0].data).toEqual([1, 3, 6, 10])
            })

            it('leaves data unchanged when cumulative is false', () => {
                const config = buildLineConfig(
                    makeProps({
                        data: [makeSeries({ data: [1, 2, 3] })],
                        cumulative: false,
                    })
                )
                expect(config.data.datasets[0].data).toEqual([1, 2, 3])
            })
        })

        describe('stacked mode', () => {
            it('sets stacked flag on x and y axes', () => {
                const config = buildLineConfig(makeProps({ stacked: true }))
                const scales = (config.options as { scales: Record<string, { stacked?: boolean }> }).scales
                expect(scales.x.stacked).toBe(true)
                expect(scales.y.stacked).toBe(true)
            })

            it('does not set stacked flag when stacked is false', () => {
                const config = buildLineConfig(makeProps({ stacked: false }))
                const scales = (config.options as { scales: Record<string, { stacked?: unknown }> }).scales
                expect(scales.y.stacked).toBeUndefined()
            })
        })

        describe('percent stacked mode', () => {
            it('enables stacked100 plugin and stacked axes', () => {
                const config = buildLineConfig(makeProps({ percentStacked: true }))
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
                        data: [
                            makeSeries({ label: 'A', color: '#ff0000' }),
                            makeSeries({ label: 'B', color: '#00ff00' }),
                        ],
                        highlightSeriesIndex: 0,
                    })
                )
                // Highlighted stays full opacity
                expect(config.data.datasets[0].borderColor).toBe('#ff0000')
                // Dimmed gets 55 border alpha and 33 background alpha
                expect(config.data.datasets[1].borderColor).toBe('#00ff0055')
                expect(config.data.datasets[1].backgroundColor).toBe('#00ff0033')
            })

            it('does not dim when highlightSeriesIndex is null', () => {
                const config = buildLineConfig(
                    makeProps({
                        data: [makeSeries({ color: '#ff0000' })],
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
                        isArea: true,
                        fillOpacity: 0.5,
                        data: [makeSeries({ color: '#ff0000' })],
                    })
                )
                // 0.5 * 255 = 127.5, rounded = 128 = 0x80
                expect(config.data.datasets[0].backgroundColor).toBe('#ff000080')
                expect(config.data.datasets[0].fill).toBe(true)
            })

            it('sets fill to "origin" when stacked', () => {
                const config = buildLineConfig(makeProps({ isArea: true, stacked: true }))
                expect(config.data.datasets[0].fill).toBe('origin')
            })

            it('sets fill to false when isArea is false and series has no fill override', () => {
                const config = buildLineConfig(makeProps({ isArea: false }))
                expect(config.data.datasets[0].fill).toBe(false)
            })

            it('respects per-series fill override', () => {
                const config = buildLineConfig(
                    makeProps({
                        isArea: false,
                        data: [makeSeries({ fill: true, color: '#ff0000' })],
                        fillOpacity: 0.5,
                    })
                )
                expect(config.data.datasets[0].fill).toBe(true)
            })
        })

        describe('compare series', () => {
            const compareSeries: ComparisonSeries[] = [
                { label: 'Series A', compareLabel: 'last week', data: [5, 10, 15], color: '#aabbcc' },
            ]

            it('appends with formatted label, dashed style, and reduced border width', () => {
                const config = buildLineConfig(makeProps({ compare: compareSeries, lineWidth: 2 }))
                expect(config.data.datasets).toHaveLength(2)
                expect(config.data.datasets[1].label).toBe('Series A (last week)')
                expect((config.data.datasets[1] as ChartDataset<'line'> & { borderDash: number[] }).borderDash).toEqual(
                    [6, 4]
                )
                expect(config.data.datasets[1].borderWidth).toBe(1.5)
            })
        })

        describe('incomplete points', () => {
            it('produces segment config with borderDash function when incompletePoints > 0', () => {
                const config = buildLineConfig(
                    makeProps({
                        data: [makeSeries({ data: [1, 2, 3, 4, 5] })],
                        incompletePoints: 2,
                    })
                )
                const dataset = config.data.datasets[0] as ChartDataset<'line'> & {
                    segment?: { borderDash: (ctx: { p1DataIndex: number }) => number[] | undefined }
                }
                expect(dataset.segment).not.toBeUndefined()
                expect(typeof dataset.segment!.borderDash).toBe('function')
            })
        })

        describe('maxSeries', () => {
            it('limits the number of datasets', () => {
                const config = buildLineConfig(
                    makeProps({
                        data: [makeSeries({ label: 'A' }), makeSeries({ label: 'B' }), makeSeries({ label: 'C' })],
                        maxSeries: 2,
                    })
                )
                expect(config.data.datasets).toHaveLength(2)
            })
        })

        describe('interpolation', () => {
            it('sets tension to 0.35 for smooth', () => {
                expect(buildLineConfig(makeProps({ interpolation: 'smooth' })).data.datasets[0].tension).toBe(0.35)
            })

            it('sets stepped to "before" for step', () => {
                expect(buildLineConfig(makeProps({ interpolation: 'step' })).data.datasets[0].stepped).toBe('before')
            })
        })

        describe('yAxisID assignment', () => {
            it('assigns "y1" when series yAxisPosition is "right"', () => {
                const config = buildLineConfig(makeProps({ data: [makeSeries({ yAxisPosition: 'right' })] }))
                expect((config.data.datasets[0] as ChartDataset<'line'> & { yAxisID: string }).yAxisID).toBe('y1')
            })
        })

        describe('hideXAxis / hideYAxis', () => {
            it('sets display to false on the respective axis', () => {
                const xConfig = buildLineConfig(makeProps({ hideXAxis: true }))
                const yConfig = buildLineConfig(makeProps({ hideYAxis: true }))
                const xScales = (xConfig.options as { scales: Record<string, { display: unknown }> }).scales
                const yScales = (yConfig.options as { scales: Record<string, { display: unknown }> }).scales
                expect(xScales.x.display).toBe(false)
                expect(yScales.y.display).toBe(false)
            })
        })
    })

    describe('buildAreaConfig', () => {
        it('enables fill with default fillOpacity of 0.1', () => {
            const config = buildAreaConfig({
                data: [makeSeries({ color: '#ff0000' })],
                labels: ['A'],
            })
            expect(config.data.datasets[0].fill).toBe(true)
            // 0.1 * 255 = 25.5, rounded = 26 = 0x1a
            expect(config.data.datasets[0].backgroundColor).toBe('#ff00001a')
        })

        it('respects explicit fillOpacity override', () => {
            const config = buildAreaConfig({
                data: [makeSeries({ color: '#ff0000' })],
                labels: ['A'],
                fillOpacity: 0.5,
            })
            expect(config.data.datasets[0].backgroundColor).toBe('#ff000080')
        })
    })
})
