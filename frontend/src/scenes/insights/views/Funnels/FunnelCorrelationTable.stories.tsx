import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'

import { mswDecorator } from '~/mocks/browser'
import funnelCorrelation from '~/mocks/fixtures/api/projects/team_id/insights/funnelCorrelation.json'
import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
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
                'api/projects/:team_id/insights/funnel/correlation/': funnelCorrelation,
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
    const filters = insight.filters
    const cachedInsight = { ...insight, short_id: dashboardItemId, filters }

    const insightProps = { dashboardItemId, doNotLoad: true, cachedInsight } as InsightLogicProps
    const querySource = filtersToQueryNode(filters)

    const dataNodeLogicProps: DataNodeLogicProps = {
        query: querySource,
        key: insightVizDataNodeKey(insightProps),
        cachedResults: getCachedResults(insightProps.cachedInsight, querySource),
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
