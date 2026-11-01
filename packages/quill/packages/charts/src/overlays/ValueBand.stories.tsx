import { Meta, StoryObj } from '@storybook/react'

import { TimeSeriesLineChart } from '../charts/TimeSeriesLineChart/TimeSeriesLineChart'
import type { Series } from '../core/types'
import { Stage, useReactiveTheme } from '../story-helpers'
import { ValueBand } from './ValueBand'

const LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const SERIES: Series[] = [{ key: 'cpu', label: 'CPU', data: [42, 55, 61, 83, 76, 91, 68] }]

const meta: Meta = {
    title: 'Components/HogCharts/ValueBand',
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<{}>

/** Threshold zones: a band per range, with a goal line at each threshold. `stroke: 'solid'` on a
 *  goal line draws it solid; the default is dashed. */
export const ThresholdZones: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <TimeSeriesLineChart
                    series={SERIES}
                    labels={LABELS}
                    theme={theme}
                    config={{
                        yAxis: { showGrid: true, min: 0, max: 100 },
                        goalLines: [
                            { value: 70, label: 'Warning', color: '#e8a317', stroke: 'solid' },
                            { value: 85, label: 'Critical', color: '#d6336c' },
                        ],
                    }}
                >
                    <ValueBand to={70} color="#2f9e44" />
                    <ValueBand from={70} to={85} color="#e8a317" />
                    <ValueBand from={85} color="#d6336c" fillOpacity={0.15} />
                </TimeSeriesLineChart>
            </Stage>
        )
    },
}
