import { Meta, Story } from '@storybook/react'
import React, { useState } from 'react'
import { ChartDisplayType, FunnelVizType, InsightColor, InsightModel, InsightShortId, InsightType } from '~/types'
import { InsightCard as InsightCardComponent } from '.'
import { DashboardPrivilegeLevel, DashboardRestrictionLevel } from 'lib/constants'
import { uuid } from 'lib/utils'

const EXAMPLE_TRENDS: InsightModel = {
    id: 1,
    short_id: 'Q79U4XDp' as InsightShortId,
    name: 'Daily Active Users',
    filters: {
        events: [
            {
                id: '$pageview',
                math: 'dau',
                type: 'events',
            },
        ],
        insight: InsightType.TRENDS,
        interval: 'day',
    },
    filters_hash: 'cache_10242f26e25fd30ec2c9721e4f90a018',
    deleted: false,
    dashboards: [1],
    layouts: {
        sm: {
            h: 5,
            w: 6,
            x: 0,
            y: 0,
        },
        xs: {
            h: 5,
            w: 1,
            x: 0,
            y: 0,
            moved: false,
            static: false,
        },
    },
    order: 0,
    color: null,
    last_refresh: '2021-12-14T12:57:57.125157Z',
    refreshing: false,
    result: [
        {
            action: {
                id: '$pageview',
                type: 'events',
                order: null,
                name: '$pageview',
                custom_name: null,
                math: 'dau',
                math_property: null,
                math_group_type_index: null,
                properties: [],
            },
            label: '$pageview',
            count: 1,
            data: [0, 1, 1, 2, 3, 5, 8, 13],
            labels: [
                '7-Dec-2021',
                '8-Dec-2021',
                '9-Dec-2021',
                '10-Dec-2021',
                '11-Dec-2021',
                '12-Dec-2021',
                '13-Dec-2021',
                '14-Dec-2021',
            ],
            days: [
                '2021-12-07',
                '2021-12-08',
                '2021-12-09',
                '2021-12-10',
                '2021-12-11',
                '2021-12-12',
                '2021-12-13',
                '2021-12-14',
            ],
            persons_urls: [
                {
                    filter: {
                        entity_id: '$pageview',
                        entity_type: 'events',
                        entity_math: 'dau',
                        date_from: '2021-12-07',
                        date_to: '2021-12-07',
                    },
                    url: 'api/projects/997/actions/people/?date_from=2021-12-07&date_to=2021-12-07&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22dau%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%5D&insight=TRENDS&interval=day&entity_id=%24pageview&entity_type=events&entity_math=dau',
                },
                {
                    filter: {
                        entity_id: '$pageview',
                        entity_type: 'events',
                        entity_math: 'dau',
                        date_from: '2021-12-08',
                        date_to: '2021-12-08',
                    },
                    url: 'api/projects/997/actions/people/?date_from=2021-12-08&date_to=2021-12-08&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22dau%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%5D&insight=TRENDS&interval=day&entity_id=%24pageview&entity_type=events&entity_math=dau',
                },
                {
                    filter: {
                        entity_id: '$pageview',
                        entity_type: 'events',
                        entity_math: 'dau',
                        date_from: '2021-12-09',
                        date_to: '2021-12-09',
                    },
                    url: 'api/projects/997/actions/people/?date_from=2021-12-09&date_to=2021-12-09&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22dau%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%5D&insight=TRENDS&interval=day&entity_id=%24pageview&entity_type=events&entity_math=dau',
                },
                {
                    filter: {
                        entity_id: '$pageview',
                        entity_type: 'events',
                        entity_math: 'dau',
                        date_from: '2021-12-10',
                        date_to: '2021-12-10',
                    },
                    url: 'api/projects/997/actions/people/?date_from=2021-12-10&date_to=2021-12-10&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22dau%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%5D&insight=TRENDS&interval=day&entity_id=%24pageview&entity_type=events&entity_math=dau',
                },
                {
                    filter: {
                        entity_id: '$pageview',
                        entity_type: 'events',
                        entity_math: 'dau',
                        date_from: '2021-12-11',
                        date_to: '2021-12-11',
                    },
                    url: 'api/projects/997/actions/people/?date_from=2021-12-11&date_to=2021-12-11&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22dau%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%5D&insight=TRENDS&interval=day&entity_id=%24pageview&entity_type=events&entity_math=dau',
                },
                {
                    filter: {
                        entity_id: '$pageview',
                        entity_type: 'events',
                        entity_math: 'dau',
                        date_from: '2021-12-12',
                        date_to: '2021-12-12',
                    },
                    url: 'api/projects/997/actions/people/?date_from=2021-12-12&date_to=2021-12-12&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22dau%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%5D&insight=TRENDS&interval=day&entity_id=%24pageview&entity_type=events&entity_math=dau',
                },
                {
                    filter: {
                        entity_id: '$pageview',
                        entity_type: 'events',
                        entity_math: 'dau',
                        date_from: '2021-12-13',
                        date_to: '2021-12-13',
                    },
                    url: 'api/projects/997/actions/people/?date_from=2021-12-13&date_to=2021-12-13&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22dau%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%5D&insight=TRENDS&interval=day&entity_id=%24pageview&entity_type=events&entity_math=dau',
                },
                {
                    filter: {
                        entity_id: '$pageview',
                        entity_type: 'events',
                        entity_math: 'dau',
                        date_from: '2021-12-14',
                        date_to: '2021-12-14',
                    },
                    url: 'api/projects/997/actions/people/?date_from=2021-12-14&date_to=2021-12-14&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22dau%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%5D&insight=TRENDS&interval=day&entity_id=%24pageview&entity_type=events&entity_math=dau',
                },
            ],
            filter: {
                date_from: '2021-12-07T00:00:00+00:00',
                date_to: '2021-12-14T12:57:57.078493+00:00',
                display: 'ActionsLineGraph',
                events: [
                    {
                        id: '$pageview',
                        type: 'events',
                        order: null,
                        name: '$pageview',
                        custom_name: null,
                        math: 'dau',
                        math_property: null,
                        math_group_type_index: null,
                        properties: [],
                    },
                ],
                insight: 'TRENDS',
                interval: 'day',
            },
        },
    ],
    created_at: '2021-12-14T11:05:45.815141Z',
    last_modified_at: '2021-12-19T14:42:21.815141Z',
    last_modified_by: {
        id: 1,
        uuid: uuid(),
        distinct_id: 'xyz',
        first_name: 'Michael',
        email: 'michael@posthog.com',
    },
    description: 'Shows the number of unique users that use your app every day.',
    updated_at: '2021-12-14T12:58:26.665942Z',
    tags: [],
    favorited: false,
    saved: false,
    created_by: null,
    is_sample: false,
    effective_privilege_level: DashboardPrivilegeLevel.CanEdit,
    effective_restriction_level: DashboardRestrictionLevel.EveryoneInProjectCanEdit,
}

const EXAMPLE_FUNNEL: InsightModel = {
    id: 15,
    short_id: 'VcnW5Of4' as InsightShortId,
    name: 'Double page view',
    filters: {
        events: [
            {
                id: '$pageview',
                name: '$pageview',
                type: 'events',
                order: 0,
            },
            {
                id: '$pageview',
                name: '$pageview',
                type: 'events',
                order: 1,
            },
        ],
        actions: [],
        display: ChartDisplayType.FunnelViz,
        insight: InsightType.FUNNELS,
        interval: 'day',
        exclusions: [],
        properties: [],
        funnel_viz_type: FunnelVizType.Steps,
    },
    filters_hash: 'cache_efe341a46f090f397007fe97d8faf263',
    order: 1,
    deleted: false,
    dashboards: [6],
    layouts: {},
    color: null,
    last_refresh: null,
    refreshing: false,
    result: [
        {
            action_id: '$pageview',
            name: '$pageview',
            custom_name: null,
            order: 0,
            people: [],
            count: 1,
            type: 'events',
            average_conversion_time: null,
            median_conversion_time: null,
            converted_people_url:
                '/api/person/funnel/?date_from=2022-02-09T00%3A00%3A00%2B00%3A00&date_to=2022-02-16T19%3A49%3A22.590606%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%5D&funnel_step=1&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100',
            dropped_people_url: null,
        },
        {
            action_id: '$pageview',
            name: '$pageview',
            custom_name: null,
            order: 1,
            people: [],
            count: 1,
            type: 'events',
            average_conversion_time: 710.4057971014493,
            median_conversion_time: 1,
            converted_people_url:
                '/api/person/funnel/?date_from=2022-02-09T00%3A00%3A00%2B00%3A00&date_to=2022-02-16T19%3A49%3A22.590606%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%5D&funnel_step=2&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100',
            dropped_people_url:
                '/api/person/funnel/?date_from=2022-02-09T00%3A00%3A00%2B00%3A00&date_to=2022-02-16T19%3A49%3A22.590606%2B00%3A00&display=FunnelViz&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+0%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%2C+%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+1%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+null%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%5D&funnel_step=-2&funnel_viz_type=steps&funnel_window_interval=14&funnel_window_interval_unit=day&insight=FUNNELS&interval=day&limit=100',
        },
    ],
    created_at: '2022-02-16T19:49:16.383715Z',
    created_by: {
        id: 1,
        uuid: '017ef865-19da-0000-3b60-1506093bf40f',
        distinct_id: '7Qj57yoNMQfmdFnZEn0Lb68RzNh7Rh5AgkubTCKK7FZ',
        first_name: 'Michael',
        email: 'michael@posthog.com',
    },
    description: '',
    updated_at: '2022-02-16T19:49:55.741547Z',
    tags: [],
    favorited: false,
    saved: false,
    last_modified_at: '2022-02-16T19:49:52.677568Z',
    last_modified_by: {
        id: 1,
        uuid: '017ef865-19da-0000-3b60-1506093bf40f',
        distinct_id: '7Qj57yoNMQfmdFnZEn0Lb68RzNh7Rh5AgkubTCKK7FZ',
        first_name: 'Michael',
        email: 'michael@posthog.com',
    },
    is_sample: false,
    effective_restriction_level: 21,
    effective_privilege_level: 37,
}

export default {
    title: 'Components/Insight Card',
    component: InsightCardComponent,
    argTypes: {
        insightName: {
            control: { type: 'text' },
            defaultValue: 'Insight title (edit in story controls)',
        },
        insightDescription: {
            control: { type: 'text' },
            defaultValue: 'Insight description (edit in story controls)',
        },
        loading: {
            control: { type: 'boolean' },
        },
        apiErrored: {
            control: { type: 'boolean' },
        },
        timedOut: {
            control: { type: 'boolean' },
        },
        highlighted: {
            control: { type: 'boolean' },
        },
    },
} as Meta

export const InsightCard: Story = (args) => {
    const [insightColor, setInsightColor] = useState<InsightColor | null>(null)
    const [wasItemRemoved, setWasItemRemoved] = useState(false)

    return (
        <div style={{ display: 'grid', gap: '1rem', gridTemplateColumns: 'repeat(2, 1fr)' }}>
            {!wasItemRemoved && (
                <InsightCardComponent
                    insight={{
                        ...EXAMPLE_TRENDS,
                        name: args.insightName,
                        description: args.insightDescription,
                        color: insightColor,
                    }}
                    loading={args.loading}
                    apiErrored={args.apiErrored}
                    highlighted={args.highlighted}
                    timedOut={args.timedOut}
                    showResizeHandles={args.resizable}
                    updateColor={setInsightColor}
                    removeFromDashboard={() => setWasItemRemoved(true)}
                    rename={() => {}}
                    duplicate={() => {}}
                />
            )}
            <InsightCardComponent
                insight={{
                    ...EXAMPLE_TRENDS,
                    name: 'Wow, this name is really super duper ginormously off the charts long! How do we even manage to fit it in an insight card without it breaking?!',
                    description:
                        'Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium doloremque laudantium, totam rem aperiam, eaque ipsa quae ab illo inventore veritatis et quasi architecto beatae vitae dicta sunt explicabo. Nemo enim ipsam voluptatem quia voluptas sit aspernatur aut odit aut fugit, sed quia consequuntur magni dolores eos qui ratione voluptatem sequi nesciunt.',
                    tags: ['every', 'green', 'bus', 'drives', 'fast', 'face'],
                }}
                rename={() => {}}
                duplicate={() => {}}
            />
            <InsightCardComponent
                insight={{ ...EXAMPLE_TRENDS, name: '', description: '', last_modified_by: null }}
                rename={() => {}}
                duplicate={() => {}}
            />
            <InsightCardComponent
                insight={{
                    ...EXAMPLE_FUNNEL,
                    short_id: 'funnel_empty' as InsightShortId,
                    filters: { ...EXAMPLE_FUNNEL.filters, events: EXAMPLE_FUNNEL.filters.events?.slice(0, 1) },
                    name: 'What a pitiful funnel',
                }}
                rename={() => {}}
                duplicate={() => {}}
            />
            <InsightCardComponent
                insight={{ ...EXAMPLE_FUNNEL, name: 'What a plentiful funnel' }}
                rename={() => {}}
                duplicate={() => {}}
            />
            <InsightCardComponent
                insight={{
                    ...EXAMPLE_TRENDS,
                    filters: { ...EXAMPLE_TRENDS.filters, display: 'totally_wrong_display_type' as ChartDisplayType },
                }}
                rename={() => {}}
                duplicate={() => {}}
            />
        </div>
    )
}
