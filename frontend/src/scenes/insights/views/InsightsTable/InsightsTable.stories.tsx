import { useState } from 'react'
import { BindLogic } from 'kea'
import { ComponentMeta, ComponentStory } from '@storybook/react'

import { insightLogic } from 'scenes/insights/insightLogic'
import { useStorybookMocks } from '~/mocks/browser'
import { InsightsTableComponent, InsightsTableComponentProps } from './InsightsTable'

export default {
    title: 'Insights/InsightsTableComponent',
    component: InsightsTableComponent,
} as ComponentMeta<typeof InsightsTableComponent>

import { AggregationType } from './insightsTableDataLogic'
import { CalcColumnState } from './insightsTableLogic'

const Template: ComponentStory<typeof InsightsTableComponent> = (props: Partial<InsightsTableComponentProps>) => {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const insight = require('../../__mocks__/trendsLineBreakdown.json')
    const insightProps = { dashboardItemId: `${insight.short_id}` }

    const [aggregation, setAggregation] = useState(AggregationType.Total)

    useStorybookMocks({
        get: {
            '/api/projects/:team_id/insights/': (_, __, ctx) => [
                ctx.status(200),
                ctx.json({
                    count: 1,
                    results: [{ ...insight, short_id: insight.short_id, id: insight.id }],
                }),
            ],
        },
    })

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <InsightsTableComponent
                aggregation={aggregation}
                setAggregationType={(state: CalcColumnState) => setAggregation(AggregationType[state])}
                isTrends
                isNonTimeSeriesDisplay={false}
                allowAggregation
                handleSeriesEditClick={() => {}}
                {...props}
            />
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

export const CanEditSeriesName = Template.bind({})
CanEditSeriesName.args = {
    canEditSeriesNameInline: true,
}
