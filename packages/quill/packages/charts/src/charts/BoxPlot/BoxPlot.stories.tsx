import { Meta, StoryObj } from '@storybook/react'

import { Stage, useReactiveTheme } from '../../story-helpers'
import { BoxPlot } from './BoxPlot'
import type { BoxPlotSeries } from './types'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function d(
    min: number,
    p25: number,
    median: number,
    mean: number,
    p75: number,
    max: number,
    day?: string
): { min: number; p25: number; median: number; mean: number; p75: number; max: number; day?: string } {
    return { min, p25, median, mean, p75, max, day }
}

const SESSION_DURATION: BoxPlotSeries[] = [
    {
        key: 'sessions',
        label: 'Session duration (s)',
        color: '',
        data: [
            d(2, 18, 42, 53, 84, 220, '2025-01-01'),
            d(3, 22, 48, 58, 90, 240, '2025-01-02'),
            d(1, 15, 38, 49, 78, 200, '2025-01-03'),
            d(4, 25, 55, 65, 100, 280, '2025-01-04'),
            d(2, 20, 50, 60, 95, 260, '2025-01-05'),
            d(3, 24, 52, 62, 98, 270, '2025-01-06'),
            d(2, 19, 45, 55, 88, 230, '2025-01-07'),
        ],
    },
]

const TWO_SERIES: BoxPlotSeries[] = [
    {
        key: 'desktop',
        label: 'Desktop',
        color: '',
        data: [
            d(2, 18, 42, 53, 84, 220),
            d(3, 22, 48, 58, 90, 240),
            d(1, 15, 38, 49, 78, 200),
            d(4, 25, 55, 65, 100, 280),
            d(2, 20, 50, 60, 95, 260),
            d(3, 24, 52, 62, 98, 270),
            d(2, 19, 45, 55, 88, 230),
        ],
    },
    {
        key: 'mobile',
        label: 'Mobile',
        color: '',
        data: [
            d(1, 10, 25, 32, 55, 140),
            d(2, 12, 28, 36, 60, 150),
            d(1, 11, 27, 33, 58, 145),
            d(3, 16, 35, 42, 70, 175),
            d(2, 14, 32, 40, 66, 160),
            d(2, 13, 30, 38, 64, 158),
            d(1, 10, 26, 33, 56, 148),
        ],
    },
]

const meta: Meta = { title: 'Components/HogCharts/BoxPlot', parameters: { layout: 'centered' } }
export default meta

type Story = StoryObj<{}>

export const SingleSeries: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <BoxPlot
                    series={SESSION_DURATION}
                    labels={SESSION_DURATION[0].data.map((datum, i) => datum?.day ?? `Day ${i}`)}
                    theme={theme}
                    config={{ showGrid: true }}
                />
            </Stage>
        )
    },
}

export const MultiSeriesGrouped: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <BoxPlot series={TWO_SERIES} labels={DAYS} theme={theme} config={{ showGrid: true }} />
            </Stage>
        )
    },
}

export const NoGrid: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <BoxPlot series={TWO_SERIES} labels={DAYS} theme={theme} />
            </Stage>
        )
    },
}

export const WithGaps: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: BoxPlotSeries[] = [
            {
                key: 'a',
                label: 'With gaps',
                color: '',
                data: [
                    d(2, 18, 42, 53, 84, 220),
                    null,
                    d(1, 15, 38, 49, 78, 200),
                    null,
                    d(2, 20, 50, 60, 95, 260),
                    d(3, 24, 52, 62, 98, 270),
                    d(2, 19, 45, 55, 88, 230),
                ],
            },
        ]
        return (
            <Stage>
                <BoxPlot series={series} labels={DAYS} theme={theme} config={{ showGrid: true }} />
            </Stage>
        )
    },
}
