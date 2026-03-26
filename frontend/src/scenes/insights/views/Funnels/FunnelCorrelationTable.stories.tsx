import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

import { mswDecorator } from '~/mocks/browser'
import funnelCorrelation from '~/mocks/fixtures/api/projects/team_id/insights/funnelCorrelation.json'
import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import { InsightLogicProps } from '~/types'

import { FunnelCorrelationTable } from './FunnelCorrelationTable'

type Story = StoryObj<typeof FunnelCorrelationTable>
const meta: Meta<typeof FunnelCorrelationTable> = {
    title: 'Insights/FunnelCorrelationTable',
    component: FunnelCorrelationTable,
    decorators: [
        mswDecorator({
            post: {
                'api/environments/:team_id/insights/funnel/correlation/': funnelCorrelation,
            },
        }),
    ],
}
export default meta

let uniqueNode = 0

const Template: StoryFn<typeof FunnelCorrelationTable> = () => {
    const [dashboardItemId] = useState(() => `FunnelCorrelationTableStory.${uniqueNode++}`)

    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const insight = require('../../../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json')
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
                <FunnelCorrelationTable />
            </BindLogic>
        </BindLogic>
    )
}

export const Default: Story = Template.bind({})
Default.args = {}
