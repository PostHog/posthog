import { Meta, StoryObj } from '@storybook/react'
import { useEffect, useState } from 'react'

import { playHoverAtFraction, Stage, useReactiveTheme } from '../../story-helpers'
import { Gauge } from './Gauge'
import type { GaugeThreshold } from './gauge-layout'

const HEALTH: GaugeThreshold[] = [
    { value: 0, color: 'var(--data-color-7)', label: 'Healthy' },
    { value: 70, color: 'var(--data-color-13)', label: 'Busy' },
    { value: 90, color: 'var(--data-color-5)', label: 'Saturated' },
]

const APDEX: GaugeThreshold[] = [
    { value: 0, color: 'var(--data-color-5)', label: 'Poor' },
    { value: 0.7, color: 'var(--data-color-13)', label: 'Fair' },
    { value: 0.85, color: 'var(--data-color-7)', label: 'Good' },
]

const meta: Meta = { title: 'Components/HogCharts/Gauge', parameters: { layout: 'centered' } }
export default meta

type Story = StoryObj<{}>

export const Basic: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={320} height={240}>
                <Gauge value={42} min={0} max={100} theme={theme} label="Requests in flight" />
            </Stage>
        )
    },
}

export const Thresholds: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={320} height={240}>
                <Gauge
                    value={78}
                    min={0}
                    max={100}
                    thresholds={HEALTH}
                    theme={theme}
                    label="CPU"
                    config={{ valueFormat: { format: 'percentage' } }}
                />
            </Stage>
        )
    },
}

export const ThresholdsHovered: Story = {
    render: Thresholds.render,
    play: async ({ canvasElement }) => {
        await playHoverAtFraction(canvasElement, 0.5, 0.25)
    },
}

export const TargetMarker: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={320} height={240}>
                <Gauge
                    value={0.91}
                    min={0}
                    max={1}
                    thresholds={APDEX}
                    target={{ value: 0.94, label: 'SLO' }}
                    theme={theme}
                    label="Apdex"
                    config={{ valueFormat: { decimalPlaces: 2 } }}
                />
            </Stage>
        )
    },
}

export const NullValue: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={320} height={240}>
                <Gauge value={null} min={0} max={100} thresholds={HEALTH} theme={theme} label="CPU" />
            </Stage>
        )
    },
}

export const Durations: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={320} height={240}>
                <Gauge
                    value={412}
                    min={0}
                    max={1000}
                    thresholds={[
                        { value: 0, color: 'var(--data-color-7)' },
                        { value: 300, color: 'var(--data-color-13)' },
                        { value: 800, color: 'var(--data-color-5)' },
                    ]}
                    target={300}
                    theme={theme}
                    label="p95 latency"
                    config={{ valueFormat: { format: 'duration_ms' } }}
                />
            </Stage>
        )
    },
}

export const Shapes: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <div className="flex gap-4">
                {[180, 240, 300, 360].map((sweepAngle) => (
                    <Stage key={sweepAngle} width={200} height={180}>
                        <Gauge
                            value={64}
                            min={0}
                            max={100}
                            thresholds={HEALTH}
                            theme={theme}
                            label={`${sweepAngle}°`}
                            config={{ sweepAngle, valueFormat: { format: 'percentage' } }}
                        />
                    </Stage>
                ))}
            </div>
        )
    },
}

export const Tiny: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <div className="flex items-end gap-4">
                <Stage width={80} height={70}>
                    <Gauge value={72} min={0} max={100} thresholds={HEALTH} theme={theme} label="CPU" />
                </Stage>
                <Stage width={100} height={90}>
                    <Gauge value={0.993} min={0.9} max={1} theme={theme} label="Availability" />
                </Stage>
                <Stage width={120} height={100}>
                    <Gauge
                        value={1_284_331_221}
                        thresholds={HEALTH}
                        theme={theme}
                        label="Bytes"
                        config={{ valueFormat: { format: 'short' } }}
                    />
                </Stage>
            </div>
        )
    },
}

export const Large: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={720} height={420}>
                <Gauge
                    value={99.62}
                    min={98}
                    max={100}
                    thresholds={[
                        { value: 98, color: 'var(--data-color-5)', label: 'Budget spent' },
                        { value: 99.5, color: 'var(--data-color-13)', label: 'At risk' },
                        { value: 99.8, color: 'var(--data-color-7)', label: 'On track' },
                    ]}
                    target={{ value: 99.9, label: 'SLO' }}
                    theme={theme}
                    label="Availability, 30 days"
                    config={{ valueFormat: { suffix: '%', decimalPlaces: 2 } }}
                />
            </Stage>
        )
    },
}

const PODS = ['7f9c', 'a1b2', 'c3d4', 'e5f6', '0a9b', '77ee', '4c21', 'b830', '19fd', 'd6e2', '5a07', '8be4'].map(
    (suffix, i) => ({
        name: `pod=checkout-${suffix}`,
        value: [12, 38, 55, 71, 93, 64, 27, 88, 49, 97, 6, 76][i],
    })
)

export const GridOfTwelve: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <div className="grid w-[720px] grid-cols-4 gap-2">
                {PODS.map((pod) => (
                    <div key={pod.name} className="flex h-[150px] flex-col">
                        <Gauge
                            value={pod.value}
                            min={0}
                            max={100}
                            thresholds={HEALTH}
                            theme={theme}
                            label={pod.name}
                            config={{ valueFormat: { format: 'percentage' } }}
                        />
                    </div>
                ))}
            </div>
        )
    },
}

export const EdgeCases: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const cases = [
            { label: 'Above max', value: 140, min: 0, max: 100 },
            { label: 'Below min', value: -12, min: 0, max: 100 },
            { label: 'Negative range', value: -18, min: -50, max: 50 },
            { label: 'min = max', value: 5, min: 5, max: 5 },
            { label: 'No range given', value: 0.42 },
            { label: 'Unsorted thresholds', value: 55, thresholds: [...HEALTH].reverse() },
            { label: 'A very long label that will not fit', value: 3_141_592.653, min: 0, max: 5_000_000 },
            { label: 'Tiny value', value: 0.4, min: 0, max: 100, thresholds: HEALTH },
        ]
        return (
            <div className="grid w-[720px] grid-cols-4 gap-2">
                {cases.map(({ label, ...rest }) => (
                    <div key={label} className="flex h-[160px] flex-col">
                        <Gauge thresholds={HEALTH} {...rest} theme={theme} label={label} />
                    </div>
                ))}
            </div>
        )
    },
}

export const Animated: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const [value, setValue] = useState<number | null>(30)
        useEffect(() => {
            const sequence = [30, 82, 95, null, 12, 64]
            let i = 0
            const id = setInterval(() => {
                i = (i + 1) % sequence.length
                setValue(sequence[i])
            }, 1500)
            return () => clearInterval(id)
        }, [])
        return (
            <Stage width={320} height={240}>
                <Gauge
                    value={value}
                    min={0}
                    max={100}
                    thresholds={HEALTH}
                    target={90}
                    theme={theme}
                    label="CPU"
                    config={{ valueFormat: { format: 'percentage' } }}
                />
            </Stage>
        )
    },
    tags: ['test-skip'],
}
