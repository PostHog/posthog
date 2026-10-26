import type { Meta, StoryObj } from '@storybook/react'

import { BarChart, type PointClickData } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { FEATURE_FLAGS } from 'lib/constants'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import { mswDecorator } from '~/mocks/browser'
import { NodeKind } from '~/queries/schema/schema-general'
import { InsightModel, InsightShortId } from '~/types'

import { DashboardInsightResultMenu } from './DashboardInsightResultMenu'

const insight = {
    id: 1,
    short_id: 'menu-demo' as InsightShortId,
    name: 'Visitors by browser',
    query: {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
            dateRange: { date_from: '2026-01-01', date_to: '2026-01-07' },
            breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
        },
    },
} as unknown as InsightModel

function Example(): JSX.Element {
    const theme = useChartTheme()
    const inspect = (point: PointClickData): void => {
        openPersonsModal({
            title: point.label,
            query: {
                kind: NodeKind.InsightActorsQuery,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                    dateRange: { date_from: '2026-01-01', date_to: '2026-01-07' },
                    breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
                },
                breakdown: point.label,
                includeRecordings: true,
            },
            additionalSelect: { matched_recordings: 'matched_recordings' },
        })
    }
    return (
        <div className="w-full max-w-2xl h-80 border rounded p-4">
            <h3>Visitors by browser</h3>
            <div className="h-60">
                <DashboardInsightResultMenu insight={insight}>
                    <BarChart
                        labels={['Chrome', 'Safari', 'Firefox']}
                        series={[{ key: 'visitors', label: 'Visitors', data: [120, 80, 40] }]}
                        theme={theme}
                        config={{ tooltip: { resolveClickToNearestSeries: true } }}
                        onPointClick={inspect}
                    />
                </DashboardInsightResultMenu>
            </div>
        </div>
    )
}

const meta: Meta = {
    title: 'Products/Dashboards/Insight result menu',
    parameters: { mockDate: '2026-01-08', layout: 'padded' },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/ActorsQuery/': {
                    hogql: "SELECT id FROM persons WHERE properties.$browser = 'Chrome'",
                    results: [[{ id: 'example-person' }, [{ session_id: 'example-session' }]]],
                },
            },
        }),
    ],
    render: () => <Example />,
}
export default meta

export const People: StoryObj = {}
export const Quill: StoryObj = { parameters: { featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV] } }
