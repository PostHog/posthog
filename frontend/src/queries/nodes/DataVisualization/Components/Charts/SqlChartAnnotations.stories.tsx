import { Meta, StoryObj } from '@storybook/react'
import { ReactNode } from 'react'

import { mswDecorator } from '~/mocks/browser'
import { ChartSettings } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { AxisSeries } from '../../dataVisualizationLogic'
import { type SqlChartProps } from './SqlChart'
import { SqlLineGraph } from './SqlLineGraph'

// Saved insight the mocked annotations are scoped to (see the `insight`-scoped annotation below).
const INSIGHT_ID = 42

// Ten consecutive daily buckets — the only x-axis shape the SQL annotations overlay renders on
// (see `areConsecutiveDailyDates`). A DATE column type is required too.
const DAYS = [
    '2023-07-01',
    '2023-07-02',
    '2023-07-03',
    '2023-07-04',
    '2023-07-05',
    '2023-07-06',
    '2023-07-07',
    '2023-07-08',
    '2023-07-09',
    '2023-07-10',
]

const xData: AxisSeries<string> = {
    column: { name: 'day', type: { name: 'DATE', isNumerical: false }, label: 'day', dataIndex: 0 },
    data: DAYS,
}

const yData: AxisSeries<number | null>[] = [
    {
        column: { name: 'signups', type: { name: 'INTEGER', isNumerical: true }, label: 'signups', dataIndex: 1 },
        data: [120, 160, 140, 200, 240, 220, 300, 280, 340, 360],
        settings: {},
    },
]

const storyUser = {
    id: 1,
    uuid: '0188cbcf-2391-0000-1868-14fb987285c5',
    distinct_id: 'storybook-user',
    first_name: 'Story',
    email: 'story@posthog.com',
}

const annotation = (id: number, date: string, content: string, scope: string, dashboardItem: number | null): any => ({
    id,
    content,
    date_marker: `${date}T12:00:00Z`,
    creation_type: 'USR',
    dashboard_item: dashboardItem,
    created_by: storyUser,
    created_at: `${date}T12:00:00Z`,
    updated_at: `${date}T12:00:00Z`,
    deleted: false,
    scope,
})

// Covers the three cases in one chart: an emoji annotation, a lone (single) annotation on a day,
// and two annotations sharing a day (multi — rendered as a count badge).
const annotations = [
    annotation(1, '2023-07-02', '🚀 Big launch', 'project', null),
    annotation(2, '2023-07-05', 'Pricing page shipped', 'insight', INSIGHT_ID),
    annotation(3, '2023-07-08', 'Bug fix deployed', 'organization', null),
    annotation(4, '2023-07-08', 'Marketing campaign started', 'project', null),
]

const meta: Meta<typeof SqlLineGraph> = {
    title: 'Insights/SqlChartAnnotations',
    component: SqlLineGraph,
    parameters: {
        layout: 'centered',
        mockDate: '2023-07-11',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/annotations/': {
                    count: annotations.length,
                    next: null,
                    previous: null,
                    results: annotations,
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof SqlLineGraph>

// SqlLineGraph fills its flex parent, so the story needs a column container with a definite height
// (mirrors SqlBarGraph / SqlPieGraph) — otherwise the chart resolves to height 0.
function Stage({ children }: { children: ReactNode }): JSX.Element {
    // eslint-disable-next-line react/forbid-dom-props
    return <div style={{ height: 420, width: 760, display: 'flex', flexDirection: 'column' }}>{children}</div>
}

const chartSettings: ChartSettings = { showLegend: true }

/** Emoji, single, and multi (count-badge) annotations rendered over a daily-bucket SQL line chart. */
export const DailyDateAxis: Story = {
    render: () => {
        const props: SqlChartProps = {
            xData,
            yData,
            visualizationType: ChartDisplayType.ActionsLineGraph,
            chartSettings,
            insightNumericId: INSIGHT_ID,
        }
        return (
            <Stage>
                <SqlLineGraph {...props} />
            </Stage>
        )
    },
}
