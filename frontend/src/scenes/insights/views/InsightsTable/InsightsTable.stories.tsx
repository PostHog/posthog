import { useState } from 'react'
import { BindLogic } from 'kea'
import { ComponentMeta, ComponentStory } from '@storybook/react'

import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightsTable } from './InsightsTable'
import { BaseMathType, InsightLogicProps } from '~/types'

export default {
    title: 'Insights/InsightsTable',
    component: InsightsTable,
} as ComponentMeta<typeof InsightsTable>

let uniqueNode = 0

const Template: ComponentStory<typeof InsightsTable> = (props, { parameters }) => {
    const [dashboardItemId] = useState(() => `InsightTableStory.${uniqueNode++}`)

    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const insight = require('../../__mocks__/trendsLineBreakdown.json')

    const insightProps = {
        dashboardItemId,
        cachedInsight: {
            ...insight,
            short_id: dashboardItemId,
            filters: { ...insight.filters, ...parameters.mergeFilters },
        },
    } as InsightLogicProps

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <InsightsTable {...props} />
        </BindLogic>
    )
}

export const Default = Template.bind({})
Default.args = {}

export const IsLegend = Template.bind({})
IsLegend.args = {
    isLegend: true,
}

export const Embedded = Template.bind({})
Embedded.args = {
    embedded: true,
}

export const Hourly = Template.bind({})
Hourly.parameters = {
    mergeFilters: { interval: 'hour' },
}

export const Aggregation = Template.bind({})
Aggregation.parameters = {
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
}

export const CanEditSeriesName = Template.bind({})
CanEditSeriesName.args = {
    canEditSeriesNameInline: true,
}
