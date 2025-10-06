import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import { BaseMathType, InsightLogicProps } from '~/types'

import { InsightsTable } from './InsightsTable'

type Story = StoryObj<typeof InsightsTable>
const meta: Meta<typeof InsightsTable> = {
    title: 'Insights/InsightsTable',
    component: InsightsTable,
}
export default meta

let uniqueNode = 0

const Template: StoryFn<typeof InsightsTable> = (props, { parameters }) => {
    const [dashboardItemId] = useState(() => `InsightTableStory.${uniqueNode++}`)

    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const insight = require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json')
    const cachedInsight = {
        ...insight,
        short_id: dashboardItemId,
        query: {
            ...insight.query,
            source: {
                ...insight.query.source,
                ...(parameters.mergeQuerySource ? parameters.mergeQuerySource : {}),
            },
        },
    }

    const insightProps = { dashboardItemId, doNotLoad: true, cachedInsight } as InsightLogicProps

    const dataNodeLogicProps: DataNodeLogicProps = {
        query: cachedInsight.query.source,
        key: insightVizDataNodeKey(insightProps),
        cachedResults: getCachedResults(cachedInsight, cachedInsight.query.source),
        doNotLoad: insightProps.doNotLoad,
    }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <InsightsTable {...props} />
            </BindLogic>
        </BindLogic>
    )
}

export const Default: Story = Template.bind({})
Default.args = {}

export const IsLegend: Story = Template.bind({})
IsLegend.args = {
    isLegend: true,
}

export const Embedded: Story = Template.bind({})
Embedded.args = {
    embedded: true,
}

export const Hourly: Story = Template.bind({})
Hourly.parameters = {
    mergeQuerySource: { interval: 'hour' },
}

export const Aggregation: Story = Template.bind({})
Aggregation.parameters = {
    mergeQuerySource: {
        series: [
            {
                event: '$pageview',
                kind: 'EventsNode',
                name: '$pageview',
                math: BaseMathType.UniqueSessions,
            },
        ],
    },
}
