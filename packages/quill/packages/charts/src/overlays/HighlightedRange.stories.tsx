import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { BarChart } from '../charts/BarChart/BarChart'
import { LineChart } from '../charts/LineChart/LineChart'
import type { DateRangeZoomData, Series } from '../core/types'
import { Stage, useReactiveTheme } from '../story-helpers'
import { HighlightedRange } from './HighlightedRange'

const LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const SERIES: Series[] = [{ key: 'visits', label: 'Visits', color: '', data: [20, 35, 28, 60, 45, 70, 52] }]

const meta: Meta = {
    title: 'Components/HogCharts/HighlightedRange',
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<{}>

export const OnBars: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <BarChart series={SERIES} labels={LABELS} theme={theme}>
                    <HighlightedRange start="Tue" end="Thu" />
                </BarChart>
            </Stage>
        )
    },
}

export const OnLines: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <LineChart series={SERIES} labels={LABELS} theme={theme}>
                    <HighlightedRange start={1} end={4} color="var(--data-color-1)" />
                </LineChart>
            </Stage>
        )
    },
}

/** Drag across the bars — the selection persists as a highlighted range. */
export const MirroringDragSelection: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const [range, setRange] = useState<DateRangeZoomData | null>(null)
        return (
            <Stage>
                <BarChart series={SERIES} labels={LABELS} theme={theme} onDateRangeZoom={(data) => setRange(data)}>
                    {range && <HighlightedRange start={range.startIndex} end={range.endIndex} />}
                </BarChart>
            </Stage>
        )
    },
}
