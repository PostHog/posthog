import '@testing-library/jest-dom'

import { cleanup, screen, waitFor } from '@testing-library/react'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { getHogChart, renderWithInsights } from '~/test/insight-testing'
import { ChartDisplayType } from '~/types'

import { AxisSeries } from '../../dataVisualizationLogic'
import { LineGraphProps } from './LineGraph'
import { SqlLineGraph } from './SqlLineGraph'

type YSettings = AxisSeries<number | null>['settings']

const stringColumn = (name: string): AxisSeries<string>['column'] => ({
    name,
    type: { name: 'STRING', isNumerical: false },
    label: name,
    dataIndex: 0,
})

const numericColumn = (name: string): AxisSeries<number | null>['column'] => ({
    name,
    type: { name: 'INTEGER', isNumerical: true },
    label: name,
    dataIndex: 1,
})

const xData = (labels: string[]): AxisSeries<string> => ({ column: stringColumn('label'), data: labels })

const ySeries = (name: string, data: (number | null)[], settings: YSettings = {}): AxisSeries<number | null> => ({
    column: numericColumn(name),
    data,
    settings,
})

const props = (overrides: Partial<LineGraphProps>): LineGraphProps => ({
    xData: xData(['Mon', 'Tue', 'Wed']),
    yData: [],
    visualizationType: ChartDisplayType.ActionsLineGraph,
    chartSettings: {},
    ...overrides,
})

const renderChart = async (overrides: Partial<LineGraphProps>): Promise<void> => {
    renderWithInsights({ component: <SqlLineGraph {...props(overrides)} /> })
    await screen.findByRole('img', { name: /chart with/i })
}

const lowestTick = (ticks: string[]): number => Math.min(...ticks.map((t) => parseFloat(t.replace(/[^0-9.eE+-]/g, ''))))

describe('SqlLineGraph', () => {
    let cleanupJsdom: () => void
    let cleanupRaf: () => void

    beforeEach(() => {
        cleanupJsdom = setupJsdom()
        cleanupRaf = setupSyncRaf()
    })

    afterEach(() => {
        cleanupRaf()
        cleanupJsdom()
        cleanup()
    })

    describe('y-axis tick formatting', () => {
        const waitForYTicks = async (): Promise<string[]> => {
            await waitFor(() => expect(getHogChart().yTicks().length).toBeGreaterThan(0))
            return getHogChart().yTicks()
        }

        it('applies the column prefix/suffix to the left-axis ticks', async () => {
            await renderChart({
                yData: [ySeries('revenue', [1200, 1400, 1300], { formatting: { prefix: '$' } })],
            })

            const ticks = await waitForYTicks()
            expect(ticks.every((tick) => tick.startsWith('$'))).toBe(true)
        })

        it('keeps quill auto-formatted ticks when the column carries no formatting', async () => {
            await renderChart({ yData: [ySeries('count', [1200, 1400, 1300])] })

            const ticks = await waitForYTicks()
            expect(ticks.some((tick) => /[$%]/.test(tick))).toBe(false)
        })

        it('formats each gutter from its own column on a dual-axis chart', async () => {
            await renderChart({
                yData: [
                    ySeries('revenue', [1200, 1400, 1300], { formatting: { prefix: '$' } }),
                    ySeries('conversion', [12, 18, 15], {
                        formatting: { suffix: '%' },
                        display: { yAxisPosition: 'right' },
                    }),
                ],
            })

            await waitFor(() => expect(getHogChart().hasRightAxis).toBe(true))
            const chart = getHogChart()
            const rightTicks = chart.yRightTicks()
            expect(chart.yTicks().every((tick) => tick.startsWith('$'))).toBe(true)
            expect(rightTicks.length).toBeGreaterThan(0)
            expect(rightTicks.every((tick) => tick.endsWith('%'))).toBe(true)
        })
    })

    describe('start at zero', () => {
        const waitForYTicks = async (): Promise<string[]> => {
            await waitFor(() => expect(getHogChart().yTicks().length).toBeGreaterThan(0))
            return getHogChart().yTicks()
        }

        it('clamps the left-axis baseline to 0 by default', async () => {
            await renderChart({ yData: [ySeries('latency', [820, 860, 840])] })

            expect(lowestTick(await waitForYTicks())).toBe(0)
        })

        it('floats the left axis to the data range when startAtZero is false', async () => {
            await renderChart({
                yData: [ySeries('latency', [820, 860, 840])],
                chartSettings: { leftYAxisSettings: { startAtZero: false } },
            })

            expect(lowestTick(await waitForYTicks())).toBeGreaterThan(0)
        })
    })
})
