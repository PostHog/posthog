import { ComponentMeta, ComponentStory } from '@storybook/react'
import { BindLogic, useMountedLogic } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useStorybookMocks } from '~/mocks/browser'
import { InsightShortId } from '~/types'
import { InsightsTableComponent, InsightsTableComponentProps } from './InsightsTable'

export default {
    title: 'Insights/InsightsTableComponent',
    component: InsightsTableComponent,
} as ComponentMeta<typeof InsightsTableComponent>

// const Insight123 = '123' as InsightShortId

// import insight from 'src/scenes/insights/__mocks__/trendsLine.json'
import insight from '../../__mocks__/trendsLineBreakdown.json'
import { AggregationType } from './insightsTableDataLogic'
import { useState } from 'react'

// const insight = require('src/scenes/insights/__mocks__/trendsLine.json')
const count = 0

const Template: ComponentStory<typeof InsightsTableComponent> = (props) => {
    const insightProps = { dashboardItemId: `${insight.short_id}${count}` }

    const [aggregation, setAggregation] = useState(AggregationType.Total)

    useStorybookMocks({
        get: {
            '/api/projects/:team_id/insights/': (_, __, ctx) => [
                // ctx.delay(100),
                ctx.status(200),
                ctx.json({
                    count: 1,
                    results: [
                        { ...insight, short_id: `${insight.short_id}${count}`, id: (insight.id ?? 0) + 1 + count },
                    ],
                }),
            ],
        },
    })

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <InsightsTableComponent aggregation={aggregation} setAggregationType={setAggregation} {...props} />
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
Hourly.args = {
    interval: 'hour',
}

export const Aggregation = Template.bind({})
Aggregation.args = {
    allowAggregation: true,
}
