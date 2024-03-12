import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { useState } from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'

import { mswDecorator } from '~/mocks/browser'
import funnelCorrelation from '~/mocks/fixtures/api/projects/team_id/insights/funnelCorrelation.json'
import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import { InsightLogicProps } from '~/types'

import { FunnelPropertyCorrelationTable } from './FunnelPropertyCorrelationTable'

type Story = StoryObj<typeof FunnelPropertyCorrelationTable>
const meta: Meta<typeof FunnelPropertyCorrelationTable> = {
    title: 'Insights/FunnelPropertyCorrelationTable',
    component: FunnelPropertyCorrelationTable,
    decorators: [
        mswDecorator({
            post: {
                'api/projects/:team_id/insights/funnel/correlation/': funnelCorrelation,
            },
        }),
        taxonomicFilterMocksDecorator,
    ],
}
export default meta

let uniqueNode = 0

const Template: StoryFn<typeof FunnelPropertyCorrelationTable> = () => {
    const [dashboardItemId] = useState(() => `FunnelPropertyCorrelationTableStory.${uniqueNode++}`)

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
                <FunnelPropertyCorrelationTable />
            </BindLogic>
        </BindLogic>
    )
}

export const Default: Story = Template.bind({})
Default.args = {}
