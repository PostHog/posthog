import { Meta, StoryObj } from '@storybook/react'

import { LineChart } from 'lib/hog-charts'
import type { LineChartConfig, Series } from 'lib/hog-charts'
import { ciRanges } from 'lib/statistics'

import { Stage, useReactiveTheme } from '../story-helpers'

const LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const CONFIG: LineChartConfig = {
    showGrid: true,
    showCrosshair: false,
}

const meta: Meta = {
    title: 'Components/HogCharts/ConfidenceIntervals',
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<{}>

export const WithConfidenceInterval: Story = {
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
                visibility: { fromTooltip: true },
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
        const theme = useReactiveTheme()
        const series: Series[] = [
            {
                key: 'visits',
                label: 'Visits',
                color: '',
                data: [20, 35, 28, 60, 45, 70, 52],
                fill: {},
                points: { radius: 3 },
                stroke: { partial: { fromIndex: 5 } },
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
        const theme = useReactiveTheme()
        const colorA = theme.colors[0]
        const colorB = theme.colors[1]
        const dataA = [40, 42, 44, 43, 55, 57, 66]
        const dataB = [38, 36, 30, 32, 28, 22, 18]
        const [lowerA, upperA] = ciRanges(dataA, 0.95)
        const [lowerB, upperB] = ciRanges(dataB, 0.95)
        const series: Series[] = [
            { key: 'visits', label: 'Visits', color: colorA, data: dataA, points: { radius: 3 } },
            {
                key: 'visits__ci',
                label: 'Visits (CI)',
                color: colorA,
                data: upperA,
                fill: { opacity: 0.2, lowerData: lowerA },
                visibility: { fromTooltip: true },
            },
            { key: 'signups', label: 'Signups', color: colorB, data: dataB, points: { radius: 3 } },
            {
                key: 'signups__ci',
                label: 'Signups (CI)',
                color: colorB,
                data: upperB,
                fill: { opacity: 0.2, lowerData: lowerB },
                visibility: { fromTooltip: true },
            },
        ]
        return (
            <Stage>
                <LineChart series={series} labels={LABELS} config={CONFIG} theme={theme} />
            </Stage>
        )
    },
}
