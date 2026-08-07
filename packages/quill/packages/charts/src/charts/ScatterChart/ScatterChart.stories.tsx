import { Meta, StoryObj } from '@storybook/react'

import { playHoverAtFraction, Stage, useReactiveTheme } from '../../story-helpers'
import { ScatterChart, type ScatterChartPoint } from './ScatterChart'

// Deterministic pseudo-random spread so snapshots stay stable across runs.
function makePoints(count: number, seed = 1): ScatterChartPoint[] {
    let state = seed
    const next = (): number => {
        state = (state * 1103515245 + 12345) & 0x7fffffff
        return state / 0x7fffffff
    }
    return Array.from({ length: count }, (_, i) => ({
        x: Math.round(next() * 1000),
        y: Math.round(next() * 500),
        label: `Org ${i + 1}`,
    }))
}

const POINTS = makePoints(40)

const CONFIG = { xAxisLabel: 'GB ingested', yAxisLabel: 'Query count' }

const meta: Meta = { title: 'Components/HogCharts/ScatterChart', parameters: { layout: 'centered' } }
export default meta

type Story = StoryObj<{}>

export const Basic: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={560} height={360}>
                <ScatterChart points={POINTS} config={CONFIG} theme={theme} />
            </Stage>
        )
    },
}

export const LogScale: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const points: ScatterChartPoint[] = Array.from({ length: 24 }, (_, i) => ({
            x: 10 ** (1 + (i % 4)),
            y: 10 ** (1 + ((i * 3) % 4)),
            label: `Point ${i + 1}`,
        }))
        return (
            <Stage width={560} height={360}>
                <ScatterChart points={points} config={{ ...CONFIG, xLogScale: true, yLogScale: true }} theme={theme} />
            </Stage>
        )
    },
}

export const SinglePoint: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={560} height={360}>
                <ScatterChart points={[{ x: 42, y: 17, label: 'Only point' }]} config={CONFIG} theme={theme} />
            </Stage>
        )
    },
}

export const Empty: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={560} height={360}>
                <ScatterChart points={[]} config={CONFIG} theme={theme} />
            </Stage>
        )
    },
}

/** Hover near the middle — captures the highlight ring and the default x/y tooltip. */
export const Hovering: Story = {
    parameters: { layout: 'fullscreen' },
    render: () => {
        const theme = useReactiveTheme()
        return (
            // eslint-disable-next-line react/forbid-dom-props
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
                <Stage width={560} height={360}>
                    <ScatterChart points={POINTS} config={CONFIG} theme={theme} />
                </Stage>
            </div>
        )
    },
    play: async ({ canvasElement }) => {
        await playHoverAtFraction(canvasElement, 0.5)
    },
}
