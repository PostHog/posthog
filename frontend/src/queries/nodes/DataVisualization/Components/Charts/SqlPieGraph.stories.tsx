import { Meta, StoryObj } from '@storybook/react'
import { ReactNode } from 'react'

import { ChartSettings } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { AxisSeries } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'
import { SqlChartProps } from './SqlChart'
import { SqlPieGraph } from './SqlPieGraph'

const meta: Meta<typeof SqlPieGraph> = {
    title: 'Insights/SqlPieGraph',
    component: SqlPieGraph,
    parameters: {
        layout: 'centered',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof SqlPieGraph>

const xData: AxisSeries<string> = {
    column: { name: 'month', type: { name: 'STRING', isNumerical: false }, label: 'month', dataIndex: 0 },
    data: ['Jan', 'Feb', 'Mar', 'Apr', 'May'],
}

const singleSeries: AxisSeries<number | null>[] = [
    {
        column: { name: 'events', type: { name: 'INTEGER', isNumerical: true }, label: 'events', dataIndex: 1 },
        data: [4200, 1800, 620, 410, 80],
        settings: {},
    },
]

const breakdownSeries: AxisBreakdownSeries<number | null>[] = [
    { name: 'Chrome', breakdownValue: 'Chrome', data: [4200], settings: { display: { color: '#4287f5' } } },
    { name: 'Safari', breakdownValue: 'Safari', data: [1800], settings: { display: { color: '#34a853' } } },
    { name: 'Firefox', breakdownValue: 'Firefox', data: [620], settings: { display: { color: '#fbbc05' } } },
    { name: 'Edge', breakdownValue: 'Edge', data: [410], settings: { display: { color: '#ea4335' } } },
]

// SqlPieGraph fills its flex parent, so the story needs a column container with a definite height —
// otherwise the chart resolves to height 0 and quill paints a 0-size canvas (mirrors TrendsPieChart).
function Stage({ children }: { children: ReactNode }): JSX.Element {
    // eslint-disable-next-line react/forbid-dom-props
    return <div style={{ height: 420, width: 760, display: 'flex', flexDirection: 'column' }}>{children}</div>
}

const render = (props: SqlChartProps): JSX.Element => (
    <Stage>
        <SqlPieGraph {...props} />
    </Stage>
)

const baseSettings: ChartSettings = { pie: { sliceContent: 'values', showTotal: true } }

export const Default: Story = {
    render: () =>
        render({
            xData,
            yData: singleSeries,
            visualizationType: ChartDisplayType.ActionsPie,
            chartSettings: baseSettings,
        }),
}

export const WithLegend: Story = {
    render: () =>
        render({
            xData,
            yData: singleSeries,
            visualizationType: ChartDisplayType.ActionsPie,
            chartSettings: { ...baseSettings, showLegend: true },
        }),
}

export const BreakdownColors: Story = {
    render: () =>
        render({
            xData,
            yData: breakdownSeries,
            visualizationType: ChartDisplayType.ActionsPie,
            chartSettings: { ...baseSettings, showLegend: true },
        }),
}

// A long-tailed category count, where the palette's look-alike pairs and its wrap both come into
// play. This is the shape the slice color ordering exists for, so it is the one worth snapshotting.
const manyCategories: AxisSeries<string> = {
    column: { name: 'intent', type: { name: 'STRING', isNumerical: false }, label: 'intent', dataIndex: 0 },
    data: Array.from({ length: 17 }, (_, index) => `Category ${index + 1}`),
}

const longTail: AxisSeries<number | null>[] = [
    {
        column: { name: 'sessions', type: { name: 'INTEGER', isNumerical: true }, label: 'sessions', dataIndex: 1 },
        data: [400, 180, 60, 40, 36, 32, 28, 24, 20, 16, 16, 12, 12, 12, 8, 8, 8],
        settings: {},
    },
]

export const ManyCategories: Story = {
    render: () =>
        render({
            xData: manyCategories,
            yData: longTail,
            visualizationType: ChartDisplayType.ActionsPie,
            chartSettings: { ...baseSettings, showLegend: true, pie: { sliceContent: 'labels' } },
        }),
}
