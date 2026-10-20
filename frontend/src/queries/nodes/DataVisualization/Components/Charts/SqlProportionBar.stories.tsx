import { Meta, StoryObj } from '@storybook/react'

import { ChartDisplayType } from '~/types'

import { AxisSeries } from '../../dataVisualizationLogic'
import { SqlProportionBar } from './SqlProportionBar'

const meta: Meta<typeof SqlProportionBar> = {
    title: 'Insights/SqlProportionBar',
    component: SqlProportionBar,
    parameters: {
        layout: 'centered',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof SqlProportionBar>

const xData: AxisSeries<string> = {
    column: { name: 'month', type: { name: 'STRING', isNumerical: false }, label: 'month', dataIndex: 0 },
    data: ['Jan', 'Feb', 'Mar', 'Apr', 'May'],
}

const yData: AxisSeries<number | null>[] = [
    {
        column: { name: 'events', type: { name: 'INTEGER', isNumerical: true }, label: 'events', dataIndex: 1 },
        data: [4200, 1800, 620, 410, 80],
        settings: {},
    },
]

export const Default: Story = {
    render: () => (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ height: 420, width: 760, display: 'flex', flexDirection: 'column' }}>
            <SqlProportionBar
                xData={xData}
                yData={yData}
                visualizationType={ChartDisplayType.ActionsProportionBar}
                chartSettings={{}}
            />
        </div>
    ),
}
