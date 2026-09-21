import { Meta, StoryObj } from '@storybook/react'

import { AxisSeries } from '../../dataVisualizationLogic'
import { SqlMetricCard } from './SqlMetricCard'

const meta: Meta<typeof SqlMetricCard> = {
    title: 'Insights/SqlMetricCard',
    component: SqlMetricCard,
    parameters: {
        layout: 'fullscreen',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof SqlMetricCard>

const xData: AxisSeries<string> = {
    column: { name: 'month', type: { name: 'STRING', isNumerical: false }, label: 'month', dataIndex: 0 },
    data: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
}

const yData: AxisSeries<number | null>[] = [
    {
        column: { name: 'revenue', type: { name: 'FLOAT', isNumerical: true }, label: 'revenue', dataIndex: 1 },
        data: [4200, 5100, 4700, 5400, 6000, 6400],
        settings: { formatting: { prefix: '$', style: 'short' } },
    },
]

export const Default: Story = {
    render: () => (
        <div className="h-screen w-full flex flex-col">
            <SqlMetricCard xData={xData} yData={yData} />
        </div>
    ),
}
