import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

import { mswDecorator } from '~/mocks/browser'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import { InsightLogicProps, InsightShortId } from '~/types'

import { TrendsLineChart } from './TrendsLineChart'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/TrendsLineChart',
    component: TrendsLineChart,
    parameters: {
        layout: 'centered',
        mockDate: '2023-07-11',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/annotations/': {
                    count: 2,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: 1,
                            content: 'Marketing campaign launched',
                            date_marker: '2023-07-05T12:00:00Z',
                            creation_type: 'USR',
                            dashboard_item: null,
                            created_by: {
                                id: 1,
                                uuid: '0188cbcf-2391-0000-1868-14fb987285c5',
                                distinct_id: 'storybook-user',
                                first_name: 'Story',
                                email: 'story@posthog.com',
                            },
                            created_at: '2023-07-05T12:00:00Z',
                            updated_at: '2023-07-05T12:00:00Z',
                            deleted: false,
                            scope: 'organization',
                        },
                        {
                            id: 2,
                            content: 'Pricing page redesign shipped',
                            date_marker: '2023-07-08T12:00:00Z',
                            creation_type: 'USR',
                            dashboard_item: null,
                            created_by: {
                                id: 1,
                                uuid: '0188cbcf-2391-0000-1868-14fb987285c5',
                                distinct_id: 'storybook-user',
                                first_name: 'Story',
                                email: 'story@posthog.com',
                            },
                            created_at: '2023-07-08T12:00:00Z',
                            updated_at: '2023-07-08T12:00:00Z',
                            deleted: false,
                            scope: 'project',
                        },
                    ],
                },
            },
        }),
    ],
}
export default meta

let uniqueNode = 0

function Stage({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ height: 360, width: 720, display: 'flex', flexDirection: 'column' }}>{children}</div>
    )
}

function renderTrendsLineChart(insightFixture: any): JSX.Element {
    const [dashboardItemId] = useState(() => `TrendsLineChartStory.${uniqueNode++}` as InsightShortId)
    const cachedInsight = { ...insightFixture, short_id: dashboardItemId }

    const insightProps: InsightLogicProps = { dashboardItemId, doNotLoad: true, cachedInsight }
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: cachedInsight.query.source,
        key: insightVizDataNodeKey(insightProps),
        cachedResults: getCachedResults(cachedInsight, cachedInsight.query.source),
        doNotLoad: true,
    }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <Stage>
                    <TrendsLineChart />
                </Stage>
            </BindLogic>
        </BindLogic>
    )
}

/* eslint-disable @typescript-eslint/no-var-requires */
export const Default: Story = {
    render: () =>
        renderTrendsLineChart(require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json')),
}

export const SingleSeries: Story = {
    render: () =>
        renderTrendsLineChart(require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json')),
}

export const Breakdown: Story = {
    render: () =>
        renderTrendsLineChart(
            require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json')
        ),
}
/* eslint-enable @typescript-eslint/no-var-requires */
