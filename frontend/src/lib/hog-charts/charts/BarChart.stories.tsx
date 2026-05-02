import { Meta, StoryObj } from '@storybook/react'

import { BarChart } from 'lib/hog-charts'
import type { BarChartConfig, Series } from 'lib/hog-charts'

import { Stage, useReactiveTheme } from '../story-helpers'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const meta: Meta = { title: 'Components/HogCharts/BarChart', parameters: { layout: 'centered' } }
export default meta

type Story = StoryObj<{}>

/** Stacked bars with a mix of positive and negative values per index. The d3 stack splits
 *  positive and negative contributions either side of the baseline, so the topmost positive
 *  series and bottommost negative series both round their cap. */
export const StackedMixedSign: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [
            { key: 'inflow', label: 'Inflow', color: '', data: [12, 18, 9, 22, 14, 20, 16] },
            { key: 'refunds', label: 'Refunds', color: '', data: [-4, -7, -3, -10, -6, -8, -5] },
            { key: 'chargebacks', label: 'Chargebacks', color: '', data: [-1, -2, -1, -3, 0, -1, -2] },
        ]
        const config: BarChartConfig = { showGrid: true, barLayout: 'stacked' }
        return (
            <Stage>
                <BarChart series={series} labels={DAYS} config={config} theme={theme} />
            </Stage>
        )
    },
}
