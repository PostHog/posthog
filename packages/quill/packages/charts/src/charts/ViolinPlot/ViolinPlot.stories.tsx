import { Meta, StoryObj } from '@storybook/react'

import { Stage, useReactiveTheme } from '../../story-helpers'
import type { ViolinPlotSeries } from './types'
import { ViolinPlot } from './ViolinPlot'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/** A small seeded generator, so every render and every snapshot draws the same observations. */
function seededRandom(seed: number): () => number {
    let state = seed
    return () => {
        state = (state + 0x6d2b79f5) | 0
        let t = Math.imul(state ^ (state >>> 15), 1 | state)
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
}

/** Right-skewed observations around `median`, like a latency or a session duration. */
function skewedValues(random: () => number, median: number, spread: number, count: number): number[] {
    return Array.from({ length: count }, () => {
        const normal = Math.sqrt(-2 * Math.log(Math.max(random(), 1e-9))) * Math.cos(2 * Math.PI * random())
        return Math.round(median * Math.exp(spread * normal) * 100) / 100
    })
}

const random = seededRandom(7)

const RESPONSE_TIME: ViolinPlotSeries[] = [
    {
        key: 'response',
        label: 'Response time (s)',
        color: '',
        data: DAYS.map((_, i) => ({ values: skewedValues(random, 4 + (i % 3), 0.35, 28 + i * 6) })),
    },
]

const BY_PLATFORM: ViolinPlotSeries[] = [
    {
        key: 'android',
        label: 'Android',
        color: '',
        data: DAYS.map((_, i) => ({ values: skewedValues(random, 4.5 + (i % 2), 0.4, 40) })),
    },
    {
        key: 'ios',
        label: 'iOS',
        color: '',
        data: DAYS.map((_, i) => ({ values: skewedValues(random, 3.5 + (i % 3) * 0.5, 0.3, 14) })),
    },
]

const meta: Meta = { title: 'Components/HogCharts/ViolinPlot', parameters: { layout: 'centered' } }
export default meta

type Story = StoryObj<{}>

export const SingleSeries: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <ViolinPlot
                    series={RESPONSE_TIME}
                    labels={DAYS}
                    theme={theme}
                    config={{ showGrid: true, yAxisLabel: 'Seconds' }}
                />
            </Stage>
        )
    },
}

export const MultiSeriesGrouped: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <ViolinPlot
                    series={BY_PLATFORM}
                    labels={DAYS}
                    theme={theme}
                    config={{ showGrid: true, legend: { show: true } }}
                />
            </Stage>
        )
    },
}

export const WithoutPoints: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <ViolinPlot
                    series={BY_PLATFORM}
                    labels={DAYS}
                    theme={theme}
                    config={{ showGrid: true, showPoints: false }}
                />
            </Stage>
        )
    },
}

export const LogScale: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <ViolinPlot
                    series={RESPONSE_TIME}
                    labels={DAYS}
                    theme={theme}
                    config={{ showGrid: true, yScaleType: 'log' }}
                />
            </Stage>
        )
    },
}

export const MissingGroup: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const [first, ...rest] = RESPONSE_TIME[0].data
        const series: ViolinPlotSeries[] = [{ ...RESPONSE_TIME[0], data: [first, null, ...rest.slice(1)] }]
        return (
            <Stage>
                <ViolinPlot series={series} labels={DAYS} theme={theme} config={{ showGrid: true }} />
            </Stage>
        )
    },
}
