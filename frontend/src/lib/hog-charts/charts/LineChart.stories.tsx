import { Meta, StoryObj } from '@storybook/react'

import { LineChart, ReferenceLine, ValueLabels } from 'lib/hog-charts'
import type { LineChartConfig, Series } from 'lib/hog-charts'
import { ciRanges, trendLine } from 'lib/statistics'

import { playHoverAtFraction, Stage, useReactiveTheme } from '../story-helpers'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const BASIC: LineChartConfig = { showGrid: true }
const HOVER: LineChartConfig = { showGrid: true, showCrosshair: true }

const SINGLE: Series[] = [{ key: 'visits', label: 'Visits', color: '', data: [20, 35, 28, 60, 45, 70, 52] }]

const PAIR: Series[] = [
    { key: 'visits', label: 'Visits', color: '', data: [20, 35, 28, 60, 45, 70, 52] },
    { key: 'signups', label: 'Sign-ups', color: '', data: [4, 8, 6, 14, 11, 19, 13] },
]

const STACK: Series[] = [
    { key: 'web', label: 'Web', color: '', data: [10, 14, 12, 22, 18, 26, 20], fill: { opacity: 0.5 } },
    { key: 'ios', label: 'iOS', color: '', data: [6, 9, 8, 12, 14, 17, 13], fill: { opacity: 0.5 } },
    { key: 'android', label: 'Android', color: '', data: [4, 6, 7, 11, 10, 14, 12], fill: { opacity: 0.5 } },
]

const meta: Meta = { title: 'Components/HogCharts/LineChart', parameters: { layout: 'centered' } }
export default meta

type Story = StoryObj<{}>

export const SingleSeries: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <LineChart series={SINGLE} labels={DAYS} config={BASIC} theme={theme} />
            </Stage>
        )
    },
}

export const MultiSeries: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <LineChart series={PAIR} labels={DAYS} config={BASIC} theme={theme} />
            </Stage>
        )
    },
}

export const StackedArea: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <LineChart series={STACK} labels={DAYS} config={BASIC} theme={theme} />
            </Stage>
        )
    },
}

export const PercentStacked: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <LineChart series={STACK} labels={DAYS} config={{ ...BASIC, percentStackView: true }} theme={theme} />
            </Stage>
        )
    },
}

export const SinglePoint: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <LineChart
                    series={[{ key: 'v', label: 'Visits', color: '', data: [42] }]}
                    labels={['Today']}
                    config={BASIC}
                    theme={theme}
                />
            </Stage>
        )
    },
}

export const ManySeries: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = Array.from({ length: 12 }, (_, i) => ({
            key: `s${i}`,
            label: `Series ${i + 1}`,
            color: '',
            data: DAYS.map((_, j) => 10 + ((i * 7 + j * 11) % 30)),
        }))
        return (
            <Stage>
                <LineChart series={series} labels={DAYS} config={BASIC} theme={theme} />
            </Stage>
        )
    },
}

export const WithZerosAndNegatives: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [{ key: 'a', label: 'Net flow', color: '', data: [0, -5, -12, 0, 8, 14, -3] }]
        return (
            <Stage>
                <LineChart series={series} labels={DAYS} config={BASIC} theme={theme} />
            </Stage>
        )
    },
}

export const Empty: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <LineChart series={[]} labels={[]} config={BASIC} theme={theme} />
            </Stage>
        )
    },
}

/** Hover at an interior point — captures tooltip + crosshair + highlight rings. */
export const HoveringInterior: Story = {
    parameters: { layout: 'fullscreen' },
    render: () => {
        const theme = useReactiveTheme()
        return (
            // eslint-disable-next-line react/forbid-dom-props
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
                <Stage>
                    <LineChart series={PAIR} labels={DAYS} config={HOVER} theme={theme} />
                </Stage>
            </div>
        )
    },
    play: async ({ canvasElement }) => {
        await playHoverAtFraction(canvasElement, 0.5)
    },
}

/** Multi-series hover with one series hidden from the tooltip via `fromTooltip`. */
export const HoveringMultiSeries: Story = {
    parameters: { layout: 'fullscreen' },
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [
            ...STACK,
            {
                key: 'baseline',
                label: 'Baseline',
                color: theme.colors[6],
                data: DAYS.map(() => 30),
                stroke: { pattern: [4, 4] },
                visibility: { fromTooltip: true, fromStack: true },
            },
        ]
        return (
            // eslint-disable-next-line react/forbid-dom-props
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
                <Stage>
                    <LineChart series={series} labels={DAYS} config={HOVER} theme={theme} />
                </Stage>
            </div>
        )
    },
    play: async ({ canvasElement }) => {
        await playHoverAtFraction(canvasElement, 0.5)
    },
}

/** Demonstrates each series-visibility flag side by side. */
export const VisibilityFlags: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const base: Series[] = [
            { key: 'a', label: 'A', color: '', data: [20, 35, 28, 60, 45, 70, 52] },
            { key: 'b', label: 'B', color: '', data: [10, 14, 12, 22, 18, 26, 20] },
            { key: 'c', label: 'C', color: '', data: [5, 9, 8, 12, 11, 16, 12] },
        ]
        const cases: { title: string; series: Series[] }[] = [
            { title: 'excluded', series: [base[0], { ...base[1], visibility: { excluded: true } }, base[2]] },
            {
                title: 'fromValueLabels',
                series: [base[0], { ...base[1], visibility: { fromValueLabels: true } }, base[2]],
            },
            {
                title: 'fromStack (auxiliary)',
                series: [
                    { ...base[0], fill: { opacity: 0.5 } },
                    { ...base[1], fill: { opacity: 0.5 } },
                    {
                        key: 'avg',
                        label: 'Moving avg',
                        color: theme.colors[6],
                        data: [12, 18, 17, 25, 24, 33, 27],
                        stroke: { pattern: [4, 4] },
                        visibility: { fromStack: true },
                    },
                ],
            },
        ]
        return (
            // eslint-disable-next-line react/forbid-dom-props
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 24 }}>
                {cases.map((c) => (
                    <Stage key={c.title}>
                        {/* eslint-disable-next-line react/forbid-dom-props */}
                        <div style={{ fontSize: 12, marginBottom: 4 }}>{c.title}</div>
                        <LineChart series={c.series} labels={DAYS} config={BASIC} theme={theme}>
                            <ValueLabels />
                        </LineChart>
                    </Stage>
                ))}
            </div>
        )
    },
}

/** Multiple overlays composed on the same chart — catches z-order / clipping regressions. */
export const CombinedOverlays: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const color = theme.colors[0]
        const data = [20, 35, 28, 60, 45, 70, 52]
        const [lower, upper] = ciRanges(data, 0.95)
        const series: Series[] = [
            { key: 'visits', label: 'Visits', color, data, points: { radius: 3 } },
            {
                key: 'visits__ci',
                label: 'Visits (CI)',
                color,
                data: upper,
                fill: { opacity: 0.2, lowerData: lower },
                visibility: { fromTooltip: true, fromValueLabels: true },
            },
            {
                key: 'visits__trend',
                label: 'Visits (trend)',
                color,
                data: trendLine(data),
                stroke: { pattern: [1, 3] },
                visibility: { fromTooltip: true, fromValueLabels: true, fromStack: true },
            },
        ]
        return (
            <Stage width={560} height={320}>
                <LineChart series={series} labels={DAYS} config={BASIC} theme={theme}>
                    <ReferenceLine value={50} label="Target" variant="goal" />
                    <ReferenceLine value="Fri" orientation="vertical" label="Launch" variant="marker" />
                    <ValueLabels />
                </LineChart>
            </Stage>
        )
    },
}

function ThrowOnRender(): never {
    throw new Error('intentional render error for ChartErrorBoundary story')
}

export const ErrorBoundary: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <LineChart series={SINGLE} labels={DAYS} config={BASIC} theme={theme}>
                    <ThrowOnRender />
                </LineChart>
            </Stage>
        )
    },
}
