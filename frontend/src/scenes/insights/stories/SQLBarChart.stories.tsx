import { Meta, StoryObj } from '@storybook/react'
import { ReactNode } from 'react'

import { LineGraphProps } from '~/queries/nodes/DataVisualization/Components/Charts/LineGraph'
import { SqlBarGraph } from '~/queries/nodes/DataVisualization/Components/Charts/SqlBarGraph'
import { AxisSeries } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { ChartDisplayType } from '~/types'

// Renders SqlBarGraph (quill TimeSeriesBarChart) in isolation, without the insight scene.

const LABELS = ['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05', '2024-01-06', '2024-01-07']

const dateColumn: AxisSeries<string>['column'] = {
    name: 'day',
    type: { name: 'DATE', isNumerical: false },
    label: 'day',
    dataIndex: 0,
}

const ySeries = (name: string, data: number[], dataIndex: number): AxisSeries<number | null> => ({
    column: { name, type: { name: 'INTEGER', isNumerical: true }, label: name, dataIndex },
    data,
    settings: {},
})

const X_DATA: AxisSeries<string> = { column: dateColumn, data: LABELS }
const Y_DATA: AxisSeries<number | null>[] = [
    ySeries('Chrome', [40, 52, 48, 61, 55, 67, 70], 1),
    ySeries('Firefox', [22, 19, 27, 24, 31, 28, 26], 2),
    ySeries('Safari', [13, 17, 12, 19, 15, 21, 18], 3),
]

const baseProps: Omit<LineGraphProps, 'visualizationType' | 'chartSettings'> = {
    xData: X_DATA,
    yData: Y_DATA,
}

function ChartStage({ children }: { children: ReactNode }): JSX.Element {
    return <div className="h-96 w-[720px] p-4">{children}</div>
}

const meta: Meta = {
    title: 'Scenes-App/Insights/SQLBarChart',
    parameters: {
        layout: 'centered',
        testOptions: { snapshotBrowsers: ['chromium'], waitForSelector: 'canvas' },
    },
}

export default meta

type Story = StoryObj<{}>

export const Bar: Story = {
    render: () => (
        <ChartStage>
            <SqlBarGraph
                {...baseProps}
                visualizationType={ChartDisplayType.ActionsBar}
                chartSettings={{ showLegend: true }}
            />
        </ChartStage>
    ),
}

export const StackedBar: Story = {
    render: () => (
        <ChartStage>
            <SqlBarGraph
                {...baseProps}
                visualizationType={ChartDisplayType.ActionsStackedBar}
                chartSettings={{ showLegend: true }}
            />
        </ChartStage>
    ),
}

export const PercentStackedBar: Story = {
    render: () => (
        <ChartStage>
            <SqlBarGraph
                {...baseProps}
                visualizationType={ChartDisplayType.ActionsStackedBar}
                chartSettings={{ showLegend: true, stackBars100: true }}
            />
        </ChartStage>
    ),
}
