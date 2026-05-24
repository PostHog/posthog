import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import { InsightLogicProps, InsightShortId } from '~/types'

import { FunnelStepsBarChart } from './FunnelStepsBarChart'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/FunnelStepsBarChart',
    component: FunnelStepsBarChart,
    parameters: {
        layout: 'centered',
        mockDate: '2022-03-12',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

let uniqueNode = 0

function Stage({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ height: 420, width: 720, display: 'flex', flexDirection: 'column' }}>{children}</div>
    )
}

function StoryRender({ insightFixture }: { insightFixture: any }): JSX.Element {
    const [dashboardItemId] = useState(() => `FunnelStepsBarChartStory.${uniqueNode++}` as InsightShortId)
    const source = insightFixture.query.source
    const cachedInsight = { ...insightFixture, short_id: dashboardItemId }

    const insightProps: InsightLogicProps = { dashboardItemId, doNotLoad: true, cachedInsight }
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: source,
        key: insightVizDataNodeKey(insightProps),
        cachedResults: getCachedResults(cachedInsight, source),
        doNotLoad: true,
    }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <Stage>
                    <FunnelStepsBarChart />
                </Stage>
            </BindLogic>
        </BindLogic>
    )
}

/* eslint-disable @typescript-eslint/no-var-requires */
const funnelStepsInsight = (): any =>
    require('../../../../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json')
const funnelStepsBreakdownInsight = (): any =>
    require('../../../../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottomBreakdown.json')

export const Default: Story = {
    render: () => <StoryRender insightFixture={funnelStepsInsight()} />,
}

export const Breakdown: Story = {
    render: () => <StoryRender insightFixture={funnelStepsBreakdownInsight()} />,
}
/* eslint-enable @typescript-eslint/no-var-requires */
