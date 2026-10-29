import { Meta, StoryObj } from '@storybook/react'

import { Stage, useReactiveTheme } from '../../story-helpers'
import { Gauge, type GaugeItem } from './Gauge'
import type { GaugeThreshold } from './gauge-geometry'

const meta: Meta = { title: 'Components/HogCharts/Gauge', parameters: { layout: 'centered' } }
export default meta

type Story = StoryObj<{}>

const THRESHOLDS: GaugeThreshold[] = [
    { value: 70, color: '#e8a317' },
    { value: 90, color: '#d6336c' },
]
const ITEMS: GaugeItem[] = [
    { key: 'api', label: 'api', value: 42, color: '#2f9e44' },
    { key: 'web', label: 'web', value: 76, color: '#2f9e44' },
    { key: 'worker', label: 'worker', value: 94, color: '#2f9e44' },
    { key: 'cron', label: 'cron', value: null, color: '#2f9e44' },
]
const percent = (v: number): string => `${Math.round(v)}%`

/** One gauge per item. The fill takes the color of the highest threshold at or below the value, and
 *  the outer bands show each threshold's range. */
export const Radial: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={640} height={200}>
                <Gauge items={ITEMS} theme={theme} thresholds={THRESHOLDS} valueFormatter={percent} />
            </Stage>
        )
    },
}

export const SingleRadial: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={220} height={180}>
                <Gauge
                    items={[{ key: 'hit-rate', label: 'Cache hit rate', value: 0.874 }]}
                    theme={theme}
                    min={0}
                    max={1}
                    valueFormatter={(v) => `${(v * 100).toFixed(1)}%`}
                />
            </Stage>
        )
    },
}

export const HorizontalBars: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={480} height={160}>
                <Gauge items={ITEMS} theme={theme} variant="bar" thresholds={THRESHOLDS} valueFormatter={percent} />
            </Stage>
        )
    },
}

export const VerticalBars: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={360} height={220}>
                <Gauge
                    items={ITEMS}
                    theme={theme}
                    variant="bar"
                    orientation="vertical"
                    thresholds={THRESHOLDS}
                    valueFormatter={percent}
                />
            </Stage>
        )
    },
}
