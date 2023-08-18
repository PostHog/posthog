import { useState } from 'react'
import { BindLogic } from 'kea'
import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'

import { BaseMathType, InsightLogicProps } from '~/types'

import { InsightsTable } from './InsightsTable'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'

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
    const insight = require('../../__mocks__/trendsLineBreakdown.json')
    const filters = { ...insight.filters, ...parameters.mergeFilters }
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
                <InsightsTable {...props} />
            </BindLogic>
        </BindLogic>
    )
}

export const Default: Story = {
    render: Template,
    args: {},
}

export const IsLegend: Story = {
    render: Template,

    args: {
        isLegend: true,
    },
}

export const Embedded: Story = {
    render: Template,

    args: {
        embedded: true,
    },
}

export const Hourly: Story = {
    render: Template,

    parameters: {
        mergeFilters: { interval: 'hour' },
    },
}

export const Aggregation: Story = {
    render: Template,

    parameters: {
        mergeFilters: {
            events: [
                {
                    id: '$pageview',
                    name: '$pageview',
                    type: 'events',
                    order: 0,
                    math: BaseMathType.UniqueSessions,
                },
            ],
        },
    },
}

export const CanEditSeriesName: Story = {
    render: Template,

    args: {
        canEditSeriesNameInline: true,
    },
}
