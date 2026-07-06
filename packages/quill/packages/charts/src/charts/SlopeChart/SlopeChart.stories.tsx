import { Meta, StoryObj } from '@storybook/react'

import type { Series } from '../../core/types'
import { Stage, useReactiveTheme } from '../../story-helpers'
import type { SlopeSeriesMeta } from './slope-data'
import { SlopeChart } from './SlopeChart'

const LABELS = ['Before', 'After']

const SERIES: Series<SlopeSeriesMeta>[] = [
    { key: 'us', label: 'US', color: '', data: [120, 185] },
    { key: 'eu', label: 'EU', color: '', data: [200, 150] },
    { key: 'apac', label: 'APAC', color: '', data: [80, 96] },
    { key: 'latam', label: 'LATAM', color: '', data: [60, 70] },
]

const meta: Meta = { title: 'Components/HogCharts/SlopeChart', parameters: { layout: 'centered' } }
export default meta

type Story = StoryObj<{}>

export const Default: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={420}>
                <SlopeChart series={SERIES} labels={LABELS} theme={theme} />
            </Stage>
        )
    },
}

/** When the last point is the current, still-accumulating period (`meta.incompleteEnd`), only the
 *  second half of each connector dashes — the start-to-mid half stays solid. */
export const IncompleteEnd: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series<SlopeSeriesMeta>[] = SERIES.map((s) => ({ ...s, meta: { incompleteEnd: true } }))
        return (
            <Stage width={420}>
                <SlopeChart series={series} labels={LABELS} theme={theme} />
            </Stage>
        )
    },
}

export const WithoutSeriesLabels: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={420}>
                <SlopeChart series={SERIES} labels={LABELS} config={{ showSeriesLabels: false }} theme={theme} />
            </Stage>
        )
    },
}

/** Two near-flat series crowd the same vertical band as a steep one — the steepest line keeps its
 *  name label and the low-change ones are dropped. */
export const CollidingLabels: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series<SlopeSeriesMeta>[] = [
            { key: 'rocket', label: 'Rocket', color: '', data: [40, 198] },
            { key: 'flat-a', label: 'Flat A', color: '', data: [196, 200] },
            { key: 'flat-b', label: 'Flat B', color: '', data: [200, 202] },
        ]
        return (
            <Stage width={420}>
                <SlopeChart series={series} labels={LABELS} theme={theme} />
            </Stage>
        )
    },
}

/** Per-series control of which value labels show via `meta`. */
export const PerSeriesValueLabels: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series<SlopeSeriesMeta>[] = [
            { key: 'us', label: 'US', color: '', data: [120, 185], meta: { showStartLabel: false } },
            { key: 'eu', label: 'EU', color: '', data: [200, 150], meta: { showEndLabel: false } },
            { key: 'apac', label: 'APAC', color: '', data: [80, 96] },
        ]
        return (
            <Stage width={420}>
                <SlopeChart series={series} labels={LABELS} theme={theme} />
            </Stage>
        )
    },
}

export const WithLegend: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={420} height={320}>
                <SlopeChart series={SERIES} labels={LABELS} config={{ legend: { show: true } }} theme={theme} />
            </Stage>
        )
    },
}

export const LegendRight: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={560} height={280}>
                <SlopeChart
                    series={SERIES}
                    labels={LABELS}
                    config={{ legend: { show: true, position: 'right' } }}
                    theme={theme}
                />
            </Stage>
        )
    },
}

export const Empty: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={420}>
                <SlopeChart series={[]} labels={LABELS} theme={theme} />
            </Stage>
        )
    },
}
