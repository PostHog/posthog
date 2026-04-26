import { Meta, StoryObj } from '@storybook/react'

import { buildTheme } from 'lib/charts/utils/theme'
import { LineChart } from 'lib/hog-charts'
import type { LineChartConfig, Series } from 'lib/hog-charts'
import { ciRanges } from 'lib/statistics'

const LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

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
    title: 'Components/HogCharts/ConfidenceIntervals',
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<{}>

export const WithConfidenceInterval: Story = {
    render: () => {
        const theme = buildTheme()
        const data = [20, 35, 28, 60, 45, 70, 52]
        const [lower, upper] = ciRanges(data, 0.95)
        const series: Series[] = [
            {
                key: 'visits',
                label: 'Visits',
                color: 'var(--brand-blue)',
                data,
                pointRadius: 3,
            },
            {
                key: 'visits__ci',
                label: 'Visits (CI)',
                color: 'var(--brand-blue)',
                data: upper,
                fillBetweenData: lower,
                fillArea: true,
                fillOpacity: 0.2,
                pointRadius: 0,
                hideFromTooltip: true,
            },
        ]
        return (
            <Stage>
                <LineChart series={series} labels={LABELS} config={CONFIG} theme={theme} />
            </Stage>
        )
    },
}

export const AreaChartWithHatching: Story = {
    render: () => {
        const theme = buildTheme()
        const series: Series[] = [
            {
                key: 'visits',
                label: 'Visits',
                color: 'var(--brand-blue)',
                data: [20, 35, 28, 60, 45, 70, 52],
                fillArea: true,
                pointRadius: 3,
                dashedFromIndex: 5,
            },
        ]
        return (
            <Stage>
                <LineChart series={series} labels={LABELS} config={CONFIG} theme={theme} />
            </Stage>
        )
    },
}

export const MultiSeriesWithCI: Story = {
    render: () => {
        const theme = buildTheme()
        const dataA = [40, 42, 44, 43, 55, 57, 66]
        const dataB = [38, 36, 30, 32, 28, 22, 18]
        const [lowerA, upperA] = ciRanges(dataA, 0.95)
        const [lowerB, upperB] = ciRanges(dataB, 0.95)
        const series: Series[] = [
            {
                key: 'visits',
                label: 'Visits',
                color: 'var(--brand-blue)',
                data: dataA,
                pointRadius: 3,
            },
            {
                key: 'visits__ci',
                label: 'Visits (CI)',
                color: 'var(--brand-blue)',
                data: upperA,
                fillBetweenData: lowerA,
                fillArea: true,
                fillOpacity: 0.2,
                pointRadius: 0,
                hideFromTooltip: true,
            },
            {
                key: 'signups',
                label: 'Signups',
                color: 'var(--brand-red)',
                data: dataB,
                pointRadius: 3,
            },
            {
                key: 'signups__ci',
                label: 'Signups (CI)',
                color: 'var(--brand-red)',
                data: upperB,
                fillBetweenData: lowerB,
                fillArea: true,
                fillOpacity: 0.2,
                pointRadius: 0,
                hideFromTooltip: true,
            },
        ]
        return (
            <Stage>
                <LineChart series={series} labels={LABELS} config={CONFIG} theme={theme} />
            </Stage>
        )
    },
}
