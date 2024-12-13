import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { humanFriendlyNumber } from 'lib/utils'

import { cohortsModel } from '~/models/cohortsModel'

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
    formula: true,
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
