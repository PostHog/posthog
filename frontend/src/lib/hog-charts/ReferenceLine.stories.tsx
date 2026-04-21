import { Meta, StoryObj } from '@storybook/react'

import { buildTheme } from 'lib/charts/utils/theme'
import { LineChart } from 'lib/hog-charts'
import type { LineChartConfig, Series } from 'lib/hog-charts'
import { ReferenceLine } from 'lib/hog-charts/overlays/ReferenceLine'
import type { ReferenceLineFillSide, ReferenceLineVariant } from 'lib/hog-charts/overlays/ReferenceLine'

const LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const SERIES: Series[] = [
    {
        key: 'visits',
        label: 'Visits',
        color: 'var(--brand-blue)',
        data: [20, 35, 28, 60, 45, 70, 52],
    },
]

const CONFIG: LineChartConfig = {
    showGrid: true,
    showCrosshair: false,
}

function Stage({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ height: 280, width: 480, display: 'flex', flexDirection: 'column' }}>{children}</div>
    )
}

const meta: Meta = {
    title: 'Components/HogCharts/ReferenceLine',
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<{}>

export const HorizontalGoal: Story = {
    render: () => {
        const theme = buildTheme()
        return (
            <Stage>
                <LineChart series={SERIES} labels={LABELS} config={CONFIG} theme={theme}>
                    <ReferenceLine value={50} label="Target" variant="goal" />
                </LineChart>
            </Stage>
        )
    },
}

export const HorizontalVariants: Story = {
    render: () => {
        const theme = buildTheme()
        const variants: { variant: ReferenceLineVariant; value: number; label: string }[] = [
            { variant: 'goal', value: 30, label: 'Goal' },
            { variant: 'alert', value: 55, label: 'Alert' },
            { variant: 'marker', value: 15, label: 'Marker' },
        ]
        return (
            <Stage>
                <LineChart series={SERIES} labels={LABELS} config={CONFIG} theme={theme}>
                    {variants.map((v) => (
                        <ReferenceLine key={v.variant} {...v} />
                    ))}
                </LineChart>
            </Stage>
        )
    },
}

export const VerticalReferenceLines: Story = {
    render: () => {
        const theme = buildTheme()
        return (
            <Stage>
                <LineChart series={SERIES} labels={LABELS} config={CONFIG} theme={theme}>
                    <ReferenceLine value="Wed" orientation="vertical" label="Launch" variant="marker" />
                    <ReferenceLine value="Sat" orientation="vertical" label="Peak" variant="alert" />
                </LineChart>
            </Stage>
        )
    },
}

export const FillSides: Story = {
    render: () => {
        const theme = buildTheme()
        const rows: { side: ReferenceLineFillSide; orientation: 'horizontal' | 'vertical'; value: number | string }[] =
            [
                { side: 'above', orientation: 'horizontal', value: 45 },
                { side: 'below', orientation: 'horizontal', value: 45 },
                { side: 'left', orientation: 'vertical', value: 'Thu' },
                { side: 'right', orientation: 'vertical', value: 'Thu' },
            ]
        return (
            // eslint-disable-next-line react/forbid-dom-props
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
                {rows.map((row) => (
                    <Stage key={`${row.orientation}-${row.side}`}>
                        {/* eslint-disable-next-line react/forbid-dom-props */}
                        <div style={{ fontSize: 12, marginBottom: 4 }}>
                            fillSide="{row.side}" ({row.orientation})
                        </div>
                        <LineChart series={SERIES} labels={LABELS} config={CONFIG} theme={theme}>
                            <ReferenceLine
                                value={row.value}
                                orientation={row.orientation}
                                fillSide={row.side}
                                label={row.side}
                                variant="alert"
                            />
                        </LineChart>
                    </Stage>
                ))}
            </div>
        )
    },
}

export const LabelStartVsEnd: Story = {
    render: () => {
        const theme = buildTheme()
        return (
            // eslint-disable-next-line react/forbid-dom-props
            <div style={{ display: 'flex', gap: 24 }}>
                <Stage>
                    <LineChart series={SERIES} labels={LABELS} config={CONFIG} theme={theme}>
                        <ReferenceLine value={50} label="start anchored" labelPosition="start" />
                    </LineChart>
                </Stage>
                <Stage>
                    <LineChart series={SERIES} labels={LABELS} config={CONFIG} theme={theme}>
                        <ReferenceLine value={50} label="end anchored" labelPosition="end" />
                    </LineChart>
                </Stage>
            </div>
        )
    },
}
