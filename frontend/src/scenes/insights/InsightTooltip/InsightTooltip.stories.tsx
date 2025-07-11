import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { humanFriendlyNumber } from 'lib/utils'

import { cohortsModel } from '~/models/cohortsModel'
import { InsightType } from '~/types'

import { InsightTooltip } from './InsightTooltip'
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
        },
    ],
}

type Story = StoryObj<typeof InsightTooltip>
const meta: Meta<typeof InsightTooltip> = {
    title: 'Components/InsightTooltip',
    component: InsightTooltip,
    args: {
        date: data.date,
        timezone: data.timezone,
        seriesData: data.seriesData as any,
        hideColorCol: false,
        renderCount: (value: number): string => `${value}`,
        renderSeries: (value) => value,
        groupTypeLabel: 'people',
    },
    tags: ['test-skip'], // FIXME: The InWrapper story fails at locator.screenshot() for some reason
}
export default meta

const BasicTemplate: StoryFn<typeof InsightTooltip> = (props: InsightTooltipProps) => {
    useMountedLogic(cohortsModel)

    return <InsightTooltip {...props} />
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {}

export const Columns: Story = BasicTemplate.bind({})
Columns.args = {
    seriesData: [
        {
            id: 0,
            dataIndex: 3,
            datasetIndex: 2,
            order: 1,
            dotted: false,
            breakdown_value: 'Safari',
            action: {
                days: [
                    '2025-05-29T00:00:00Z',
                    '2025-05-30T00:00:00Z',
                    '2025-05-31T00:00:00Z',
                    '2025-06-01T00:00:00Z',
                    '2025-06-02T00:00:00Z',
                    '2025-06-03T00:00:00Z',
                    '2025-06-04T00:00:00Z',
                    '2025-06-05T00:00:00Z',
                ],
                id: '$autocapture',
                type: 'events',
                order: 1,
                name: '$autocapture',
                custom_name: null,
                math: 'total',
                math_property: null,
                math_hogql: null,
                math_group_type_index: null,
            },
            label: '$autocapture - Safari',
            color: '#42827e',
            count: 0,
            filter: {
                insight: InsightType.TRENDS,
                properties: [],
                filter_test_accounts: true,
                date_to: '2025-06-05T23:59:59.999999Z',
                date_from: '2025-05-29T00:00:00Z',
                entity_type: 'events',
                interval: 'day',
                breakdown: '$browser',
                breakdown_type: 'event',
            },
        },
        {
            id: 1,
            dataIndex: 3,
            datasetIndex: 0,
            order: 0,
            dotted: false,
            breakdown_value: 'Chrome',
            action: {
                days: [
                    '2025-05-29T00:00:00Z',
                    '2025-05-30T00:00:00Z',
                    '2025-05-31T00:00:00Z',
                    '2025-06-01T00:00:00Z',
                    '2025-06-02T00:00:00Z',
                    '2025-06-03T00:00:00Z',
                    '2025-06-04T00:00:00Z',
                    '2025-06-05T00:00:00Z',
                ],
                id: '$pageview',
                type: 'events',
                order: 0,
                name: '$pageview',
                custom_name: 'Pageview of people with very long names like this text',
                math: 'total',
                math_property: null,
                math_hogql: null,
                math_group_type_index: null,
            },
            label: '$pageview - Chrome',
            color: '#1d4aff',
            count: 0,
            filter: {
                insight: InsightType.TRENDS,
                properties: [],
                filter_test_accounts: true,
                date_to: '2025-06-05T23:59:59.999999Z',
                date_from: '2025-05-29T00:00:00Z',
                entity_type: 'events',
                interval: 'day',
                breakdown: '$browser',
                breakdown_type: 'event',
            },
        },
        {
            id: 2,
            dataIndex: 3,
            datasetIndex: 1,
            order: 0,
            dotted: false,
            breakdown_value: 'Safari',
            action: {
                days: [
                    '2025-05-29T00:00:00Z',
                    '2025-05-30T00:00:00Z',
                    '2025-05-31T00:00:00Z',
                    '2025-06-01T00:00:00Z',
                    '2025-06-02T00:00:00Z',
                    '2025-06-03T00:00:00Z',
                    '2025-06-04T00:00:00Z',
                    '2025-06-05T00:00:00Z',
                ],
                id: '$pageview',
                type: 'events',
                order: 0,
                name: '$pageview',
                custom_name: 'Pageview of people with very long names like this text',
                math: 'total',
                math_property: null,
                math_hogql: null,
                math_group_type_index: null,
            },
            label: '$pageview - Safari',
            color: '#621da6',
            count: 0,
            filter: {
                insight: InsightType.TRENDS,
                properties: [],
                filter_test_accounts: true,
                date_to: '2025-06-05T23:59:59.999999Z',
                date_from: '2025-05-29T00:00:00Z',
                entity_type: 'events',
                interval: 'day',
                breakdown: '$browser',
                breakdown_type: 'event',
            },
        },
    ],
}

export function InWrapper(): JSX.Element {
    useMountedLogic(cohortsModel)

    return (
        <div className="min-h-50">
            <div className="InsightTooltipWrapper">
                <InsightTooltip
                    date={data.date}
                    timezone={data.timezone}
                    seriesData={data.seriesData as any}
                    renderCount={(value: number): string => humanFriendlyNumber(value)}
                    renderSeries={(value, datum) => {
                        const hasBreakdown = datum.breakdown_value !== undefined && !!datum.breakdown_value
                        return (
                            <div className="datum-label-column">
                                <SeriesLetter
                                    className="mr-2"
                                    hasBreakdown={hasBreakdown}
                                    seriesIndex={datum?.action?.order ?? datum.id}
                                    seriesColor={datum.color}
                                />
                                {value}
                            </div>
                        )
                    }}
                    groupTypeLabel="people"
                />
            </div>
        </div>
    )
}
