import { Meta, Story } from '@storybook/react'
import React, { useState } from 'react'
import { Provider as KeaProvider } from 'kea'
import { initKea } from '~/initKea'
import { InsightColor, InsightModel, InsightShortId, InsightType } from '~/types'
import { InsightCard as InsightCardComponent } from '.'

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
    dashboard: 1,
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
            data: [0, 0, 0, 0, 0, 0, 0, 1],
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
                    url: 'api/projects/1/actions/people/?date_from=2021-12-07&date_to=2021-12-07&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22dau%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%5D&insight=TRENDS&interval=day&entity_id=%24pageview&entity_type=events&entity_math=dau',
                },
                {
                    filter: {
                        entity_id: '$pageview',
                        entity_type: 'events',
                        entity_math: 'dau',
                        date_from: '2021-12-08',
                        date_to: '2021-12-08',
                    },
                    url: 'api/projects/1/actions/people/?date_from=2021-12-08&date_to=2021-12-08&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22dau%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%5D&insight=TRENDS&interval=day&entity_id=%24pageview&entity_type=events&entity_math=dau',
                },
                {
                    filter: {
                        entity_id: '$pageview',
                        entity_type: 'events',
                        entity_math: 'dau',
                        date_from: '2021-12-09',
                        date_to: '2021-12-09',
                    },
                    url: 'api/projects/1/actions/people/?date_from=2021-12-09&date_to=2021-12-09&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22dau%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%5D&insight=TRENDS&interval=day&entity_id=%24pageview&entity_type=events&entity_math=dau',
                },
                {
                    filter: {
                        entity_id: '$pageview',
                        entity_type: 'events',
                        entity_math: 'dau',
                        date_from: '2021-12-10',
                        date_to: '2021-12-10',
                    },
                    url: 'api/projects/1/actions/people/?date_from=2021-12-10&date_to=2021-12-10&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22dau%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%5D&insight=TRENDS&interval=day&entity_id=%24pageview&entity_type=events&entity_math=dau',
                },
                {
                    filter: {
                        entity_id: '$pageview',
                        entity_type: 'events',
                        entity_math: 'dau',
                        date_from: '2021-12-11',
                        date_to: '2021-12-11',
                    },
                    url: 'api/projects/1/actions/people/?date_from=2021-12-11&date_to=2021-12-11&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22dau%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%5D&insight=TRENDS&interval=day&entity_id=%24pageview&entity_type=events&entity_math=dau',
                },
                {
                    filter: {
                        entity_id: '$pageview',
                        entity_type: 'events',
                        entity_math: 'dau',
                        date_from: '2021-12-12',
                        date_to: '2021-12-12',
                    },
                    url: 'api/projects/1/actions/people/?date_from=2021-12-12&date_to=2021-12-12&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22dau%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%5D&insight=TRENDS&interval=day&entity_id=%24pageview&entity_type=events&entity_math=dau',
                },
                {
                    filter: {
                        entity_id: '$pageview',
                        entity_type: 'events',
                        entity_math: 'dau',
                        date_from: '2021-12-13',
                        date_to: '2021-12-13',
                    },
                    url: 'api/projects/1/actions/people/?date_from=2021-12-13&date_to=2021-12-13&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22dau%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%5D&insight=TRENDS&interval=day&entity_id=%24pageview&entity_type=events&entity_math=dau',
                },
                {
                    filter: {
                        entity_id: '$pageview',
                        entity_type: 'events',
                        entity_math: 'dau',
                        date_from: '2021-12-14',
                        date_to: '2021-12-14',
                    },
                    url: 'api/projects/1/actions/people/?date_from=2021-12-14&date_to=2021-12-14&display=ActionsLineGraph&events=%5B%7B%22id%22%3A+%22%24pageview%22%2C+%22type%22%3A+%22events%22%2C+%22order%22%3A+null%2C+%22name%22%3A+%22%24pageview%22%2C+%22custom_name%22%3A+null%2C+%22math%22%3A+%22dau%22%2C+%22math_property%22%3A+null%2C+%22math_group_type_index%22%3A+null%2C+%22properties%22%3A+%5B%5D%7D%5D&insight=TRENDS&interval=day&entity_id=%24pageview&entity_type=events&entity_math=dau',
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
    description: 'Shows the number of unique users that use your app every day.',
    updated_at: '2021-12-14T12:58:26.665942Z',
    tags: ['demo', 'faux'],
    favorited: false,
    saved: false,
    created_by: null,
    is_sample: false,
}

export default {
    title: 'PostHog/Components',
    parameters: { options: { showPanel: true } },
    argTypes: {
        insightName: {
            control: { type: 'text' },
            defaultValue: EXAMPLE_TRENDS.name,
        },
        insightDescription: {
            control: { type: 'text' },
            defaultValue: EXAMPLE_TRENDS.description,
        },
        loading: {
            control: { type: 'boolean' },
        },
        apiError: {
            control: { type: 'boolean' },
        },
        highlighted: {
            control: { type: 'boolean' },
        },
    },
} as Meta

export const InsightCard: Story = (args) => {
    initKea()

    const [insightColor, setInsightColor] = useState<InsightColor | null>(null)
    const [wasItemRemoved, setWasItemRemoved] = useState(false)

    return (
        <KeaProvider>
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
                        apiError={args.apiError}
                        highlighted={args.highlighted}
                        showResizeHandles={args.resizable}
                        updateColor={setInsightColor}
                        removeFromDashboard={() => setWasItemRemoved(true)}
                        refresh={() => {}}
                        rename={() => {}}
                        duplicate={() => {}}
                        moveToDashboard={() => {}}
                    />
                )}
                <InsightCardComponent
                    insight={{
                        ...EXAMPLE_TRENDS,
                        name: 'Wow, this name is really really long! How do we even manage to fit it into an insight card?!',
                        description:
                            'Neque porro quisquam est qui dolorem ipsum quia dolor sit amet, consectetur, adipisci velit.',
                        tags: ['every', 'green', 'bus', 'drives', 'fast', 'face'],
                    }}
                    loading={false}
                    apiError={false}
                    highlighted={false}
                    showResizeHandles={false}
                    updateColor={() => {}}
                    removeFromDashboard={() => {}}
                    refresh={() => {}}
                    rename={() => {}}
                    duplicate={() => {}}
                    moveToDashboard={() => {}}
                />
                <InsightCardComponent
                    insight={{ ...EXAMPLE_TRENDS, name: '', description: '', tags: [] }}
                    loading={false}
                    apiError={false}
                    highlighted={false}
                    showResizeHandles={false}
                    updateColor={() => {}}
                    removeFromDashboard={() => {}}
                    refresh={() => {}}
                    rename={() => {}}
                    duplicate={() => {}}
                    moveToDashboard={() => {}}
                />
            </div>
        </KeaProvider>
    )
}
