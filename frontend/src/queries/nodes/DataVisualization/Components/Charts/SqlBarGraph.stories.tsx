import { Meta, StoryObj } from '@storybook/react'
import { ReactNode } from 'react'

import { ChartSettings } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { AxisSeries } from '../../dataVisualizationLogic'
import { LineGraphProps } from './LineGraph'
import { SqlBarGraph } from './SqlBarGraph'

const meta: Meta<typeof SqlBarGraph> = {
    title: 'Insights/SqlBarGraph',
    component: SqlBarGraph,
    parameters: {
        layout: 'centered',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof SqlBarGraph>

const xData: AxisSeries<string> = {
    column: { name: 'month', type: { name: 'STRING', isNumerical: false }, label: 'month', dataIndex: 0 },
    data: ['Jan', 'Feb', 'Mar', 'Apr', 'May'],
}

const numericSeries = (name: string, dataIndex: number, data: (number | null)[]): AxisSeries<number | null> => ({
    column: { name, type: { name: 'INTEGER', isNumerical: true }, label: name, dataIndex },
    data,
    settings: {},
})

const positiveSeries: AxisSeries<number | null>[] = [
    numericSeries('signups', 1, [420, 380, 510, 460, 550]),
    numericSeries('upgrades', 2, [120, 140, 90, 160, 130]),
]

// Mixed-sign series, including a month (Mar) where the negatives outweigh the positives so the
// stack's net total dips below the baseline.
const mixedSignSeries: AxisSeries<number | null>[] = [
    numericSeries('new_mrr', 1, [400, 250, 300, 220, 280]),
    numericSeries('churned_mrr', 2, [-120, -180, -350, -80, -300]),
]

// SqlBarGraph fills its flex parent, so the story needs a column container with a definite height —
// otherwise the chart resolves to height 0 and quill paints a 0-size canvas (mirrors SqlPieGraph).
function Stage({ children }: { children: ReactNode }): JSX.Element {
    // eslint-disable-next-line react/forbid-dom-props
    return <div style={{ height: 420, width: 760, display: 'flex', flexDirection: 'column' }}>{children}</div>
}

const render = (props: LineGraphProps): JSX.Element => (
    <Stage>
        <SqlBarGraph {...props} />
    </Stage>
)

const baseSettings: ChartSettings = { showLegend: true }

export const StackedBar: Story = {
    render: () =>
        render({
            xData,
            yData: positiveSeries,
            visualizationType: ChartDisplayType.ActionsStackedBar,
            chartSettings: baseSettings,
        }),
}

/** Stacked bars with negative values render below the zero baseline (diverging stack) instead of
 *  being clamped to 0 — guards the regression fixed by wiring `divergingStack` through
 *  `buildBarChartConfig`. */
export const StackedBarWithNegativeValues: Story = {
    render: () =>
        render({
            xData,
            yData: mixedSignSeries,
            visualizationType: ChartDisplayType.ActionsStackedBar,
            chartSettings: baseSettings,
        }),
}

export const GroupedBarWithNegativeValues: Story = {
    render: () =>
        render({
            xData,
            yData: mixedSignSeries,
            visualizationType: ChartDisplayType.ActionsBar,
            chartSettings: baseSettings,
        }),
}
