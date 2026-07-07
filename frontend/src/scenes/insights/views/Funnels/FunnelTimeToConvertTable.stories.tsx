import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import { InsightLogicProps } from '~/types'

import __funnelTimeToConvert from '../../../../mocks/fixtures/api/projects/team_id/insights/funnelTimeToConvert.json'
import { FunnelTimeToConvertTable } from './FunnelTimeToConvertTable'

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Insights/FunnelTimeToConvertTable',
    component: FunnelTimeToConvertTable,
    parameters: { mockDate: '2023-03-01' },
    render: () => {
        const [dashboardItemId] = useState(() => `FunnelTimeToConvertTableStory.${uniqueNode++}`)

        // eslint-disable-next-line @typescript-eslint/no-var-requires
        const insight = __funnelTimeToConvert as any
        const cachedInsight = { ...insight, short_id: dashboardItemId }
        const insightProps = { dashboardItemId, doNotLoad: true, cachedInsight } as InsightLogicProps
        const dataNodeLogicProps: DataNodeLogicProps = {
            query: insight.query.source,
            key: insightVizDataNodeKey(insightProps),
            cachedResults: getCachedResults(insightProps.cachedInsight, insight.query.source),
            doNotLoad: insightProps.doNotLoad,
        }

        return (
            <BindLogic logic={insightLogic} props={insightProps}>
                <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                    <FunnelTimeToConvertTable />
                </BindLogic>
            </BindLogic>
        )
    },
}
export default meta

let uniqueNode = 0

export const Default: Story = {
    args: {},
}
