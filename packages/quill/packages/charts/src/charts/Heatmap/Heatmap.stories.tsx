import { Meta, StoryObj } from '@storybook/react'

import { Stage, useReactiveTheme } from '../../story-helpers'
import { Heatmap } from './Heatmap'

// A latency-over-time grid: x = 5-minute buckets, y = log 1-2-5 duration buckets. The data is
// deterministic and bimodal — a fast band (cache hits) all day plus a slow band (cache misses)
// that appears in the second half — the exact shape a latency heatmap exists to reveal.
const X_LABELS = Array.from({ length: 48 }, (_, i) => {
    const minutes = i * 5
    const h = String(8 + Math.floor(minutes / 60)).padStart(2, '0')
    const m = String(minutes % 60).padStart(2, '0')
    return `${h}:${m}`
})

const Y_LABELS = ['1ms', '2ms', '5ms', '10ms', '20ms', '50ms', '100ms', '200ms', '500ms', '1s', '2s', '5s']

function band(center: number, row: number, peak: number): number {
    const d = Math.abs(row - center)
    return Math.max(0, Math.round(peak / (1 + d * d * 2)))
}

const CELLS = Y_LABELS.map((_, row) =>
    X_LABELS.map((_, col) => {
        const wave = 1 + 0.5 * Math.sin(col / 5)
        const fast = band(2.5, row, 140 * wave)
        const slow = col > X_LABELS.length / 2 ? band(8.5, row, 30 * wave) : 0
        const noise = (row * 7 + col * 13) % 11 === 0 ? 1 : 0
        return fast + slow + noise
    })
)

const meta: Meta<typeof Heatmap> = {
    title: 'Charts/Heatmap',
    component: Heatmap,
    tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof Heatmap>

export const LatencyOverTime: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        return (
            <Stage width={720} height={320}>
                <Heatmap
                    xLabels={X_LABELS}
                    yLabels={Y_LABELS}
                    cells={CELLS}
                    theme={theme}
                    config={{
                        xTickFormatter: (label, i) => (i % 6 === 0 ? label : null),
                        xAxisLabel: 'Time',
                        yAxisLabel: 'Duration',
                    }}
                />
            </Stage>
        )
    },
}

export const LinearColorScale: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        return (
            <Stage width={720} height={320}>
                <Heatmap
                    xLabels={X_LABELS}
                    yLabels={Y_LABELS}
                    cells={CELLS}
                    theme={theme}
                    config={{
                        colorScale: 'linear',
                        xTickFormatter: (label, i) => (i % 6 === 0 ? label : null),
                    }}
                />
            </Stage>
        )
    },
}

export const ClickableCells: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        return (
            <Stage width={720} height={320}>
                <Heatmap
                    xLabels={X_LABELS}
                    yLabels={Y_LABELS}
                    cells={CELLS}
                    theme={theme}
                    config={{ xTickFormatter: (label, i) => (i % 6 === 0 ? label : null) }}
                    // eslint-disable-next-line no-console
                    onCellClick={(cell) => console.info('cell clicked', cell)}
                />
            </Stage>
        )
    },
}
