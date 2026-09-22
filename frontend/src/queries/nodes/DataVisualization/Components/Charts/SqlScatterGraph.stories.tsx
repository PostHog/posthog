import { Meta, StoryObj } from '@storybook/react'
import { ReactNode } from 'react'

import { ChartSettings } from '~/queries/schema/schema-general'

import { AxisSeries } from '../../dataVisualizationLogic'
import { SqlScatterGraph, SqlScatterGraphProps } from './SqlScatterGraph'

const meta: Meta<typeof SqlScatterGraph> = {
    title: 'Insights/SqlScatterGraph',
    component: SqlScatterGraph,
    parameters: {
        layout: 'centered',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof SqlScatterGraph>

const DURATIONS = [12, 34, 55, 61, 78, 90, 104, 130, 152, 171, 194, 210, 245, 280, 320]

const xData: AxisSeries<string> = {
    column: { name: 'session_duration', type: { name: 'INTEGER', isNumerical: true }, label: 'duration', dataIndex: 0 },
    data: DURATIONS as unknown as string[],
}

const yData: AxisSeries<number | null>[] = [
    {
        column: { name: 'revenue', type: { name: 'FLOAT', isNumerical: true }, label: 'revenue', dataIndex: 1 },
        data: [4, 11, 9, 22, 18, 31, 27, 44, 39, 58, 51, 72, 66, 88, 95],
        settings: {},
    },
]

const twoSeries: AxisSeries<number | null>[] = [
    ...yData,
    {
        column: { name: 'refunds', type: { name: 'FLOAT', isNumerical: true }, label: 'refunds', dataIndex: 2 },
        data: [1, 3, 2, 6, 4, 9, 5, 12, 8, 15, 11, 19, 14, 22, 25],
        settings: {},
    },
]

// The chart fills its flex parent, so the story needs a column container with a definite height —
// otherwise it resolves to height 0 and quill paints a 0-size canvas (mirrors SqlPieGraph).
function Stage({ children }: { children: ReactNode }): JSX.Element {
    // eslint-disable-next-line react/forbid-dom-props
    return <div style={{ height: 420, width: 760, display: 'flex', flexDirection: 'column' }}>{children}</div>
}

const render = (props: SqlScatterGraphProps): JSX.Element => (
    <Stage>
        <SqlScatterGraph {...props} />
    </Stage>
)

const baseSettings: ChartSettings = { leftYAxisSettings: { label: 'Revenue' } }

export const Default: Story = {
    render: () => render({ xData, yData, chartSettings: baseSettings }),
}

export const MultipleSeriesWithLegend: Story = {
    render: () => render({ xData, yData: twoSeries, chartSettings: { ...baseSettings, showLegend: true } }),
}
