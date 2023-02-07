import { InsightTooltip } from './InsightTooltip'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { cohortsModel } from '~/models/cohortsModel'
import { useMountedLogic } from 'kea'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { InsightTooltipProps } from './insightTooltipUtils'

const data = {
    date: '2022-08-31',
    timezone: 'UTC',
    seriesData: [
        {
            id: 0,
            dataIndex: 7,
            datasetIndex: 2,
            dotted: true,
            action: {
                id: '$pageview',
                type: 'events',
                order: 0,
                name: '$pageview',
                custom_name: 'Pageview of people with very long names like this text',
                math: 'dau',
                math_property: null,
                math_group_type_index: null,
                properties: {},
            },
            label: '$pageview',
            color: '#1d4aff',
            count: 1,
            filter: {
                breakdown_attribution_type: 'first_touch',
                date_from: '-7d',
                display: 'ActionsLineGraph',
                events: [
                    {
                        id: '$pageview',
                        type: 'events',
                        order: 0,
                        name: '$pageview',
                        custom_name: null,
                        math: 'dau',
                        math_property: null,
                        math_group_type_index: null,
                        properties: {},
                    },
                    {
                        id: 'filter added',
                        type: 'events',
                        order: 1,
                        name: 'filter added',
                        custom_name: null,
                        math: null,
                        math_property: null,
                        math_group_type_index: null,
                        properties: {},
                    },
                ],
                insight: 'TRENDS',
                interval: 'day',
                smoothing_intervals: 1,
            },
        },
        {
            id: 1,
            dataIndex: 7,
            datasetIndex: 3,
            dotted: true,
            action: {
                id: 'filter added',
                type: 'events',
                order: 1,
                name: 'filter added',
                custom_name: null,
                math: null,
                math_property: null,
                math_group_type_index: null,
                properties: {},
            },
            label: 'filter added',
            color: '#621da6',
            count: 1,
            filter: {
                breakdown_attribution_type: 'first_touch',
                date_from: '-7d',
                display: 'ActionsLineGraph',
                events: [
                    {
                        id: '$pageview',
                        type: 'events',
                        order: 0,
                        name: '$pageview',
                        custom_name: null,
                        math: 'dau',
                        math_property: null,
                        math_group_type_index: null,
                        properties: {},
                    },
                    {
                        id: 'filter added',
                        type: 'events',
                        order: 1,
                        name: 'filter added',
                        custom_name: null,
                        math: null,
                        math_property: null,
                        math_group_type_index: null,
                        properties: {},
                    },
                ],
                insight: 'TRENDS',
                interval: 'day',
                smoothing_intervals: 1,
            },
        },
    ],
}

export default {
    title: 'Components/InsightTooltip',
    component: InsightTooltip,
    argTypes: {
        date: { defaultValue: data.date },
        timezone: { defaultValue: data.timezone },
        seriesData: { defaultValue: data.seriesData as any },
        hideColorCol: { defaultValue: false },
        renderCount: { defaultValue: (value: number): string => `${value}` },
        forceEntitiesAsColumns: { defaultValue: false },
        groupTypeLabel: { defaultValue: 'people' },
    },
    parameters: {
        testOptions: { skip: true }, // FIXME: The InWrapper story fails at locator.screenshot() for some reason
    },
} as ComponentMeta<typeof InsightTooltip>

const BasicTemplate: ComponentStory<typeof InsightTooltip> = (props: InsightTooltipProps) => {
    useMountedLogic(personPropertiesModel)
    useMountedLogic(cohortsModel)

    return <InsightTooltip {...props} />
}

export const Default = BasicTemplate.bind({})
Default.args = {}

export const Columns = BasicTemplate.bind({})
Columns.args = {
    forceEntitiesAsColumns: true,
}

export function InWrapper(): JSX.Element {
    useMountedLogic(personPropertiesModel)
    useMountedLogic(cohortsModel)

    return (
        <div style={{ minHeight: 200 }}>
            <div className="InsightTooltipWrapper">
                <InsightTooltip
                    date={data.date}
                    timezone={data.timezone}
                    seriesData={data.seriesData as any}
                    renderCount={(value: number): string => `${value}`}
                    groupTypeLabel={'people'}
                />
            </div>
        </div>
    )
}
