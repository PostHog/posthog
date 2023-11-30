import { Meta } from '@storybook/react'
import { useActions } from 'kea'
import { commandBarLogic } from 'lib/components/CommandBar/commandBarLogic'
import { BarStatus } from 'lib/components/CommandBar/types'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { CommandBar } from './CommandBar'

const SEARCH_RESULT = {
    results: [
        {
            type: 'insight',
            result_id: 'NmLsyopa',
            extra_fields: {
                name: '',
                query: null,
                filters: {
                    events: [
                        {
                            id: '$pageview',
                            math: 'total',
                            name: '$pageview',
                            type: 'events',
                            order: 0,
                        },
                    ],
                    display: 'ActionsLineGraph',
                    insight: 'TRENDS',
                    interval: 'day',
                    entity_type: 'events',
                    filter_test_accounts: true,
                },
                description: '',
            },
        },
        {
            type: 'insight',
            result_id: 'QcCPEk7d',
            extra_fields: {
                name: 'Daily unique visitors over time',
                query: null,
                filters: {
                    events: [
                        {
                            id: '$pageview',
                            math: 'dau',
                            type: 'events',
                            order: 0,
                        },
                        {
                            id: null,
                            math: 'total',
                            type: 'events',
                            order: 1,
                        },
                    ],
                    date_to: null,
                    display: 'ActionsLineGraph',
                    insight: 'TRENDS',
                    interval: 'day',
                    date_from: '-6m',
                    entity_type: 'events',
                },
                description: null,
            },
        },
        {
            type: 'insight',
            result_id: '38EAleI9',
            extra_fields: {
                name: '',
                query: {
                    full: true,
                    kind: 'DataTableNode',
                    source: {
                        kind: 'HogQLQuery',
                        query: '   select event,\n          person.properties.email,\n          properties.$browser,\n          count()\n     from events\n    where {filters} -- replaced with global date and property filters\n      and person.properties.email is not null\n group by event,\n          properties.$browser,\n          person.properties.email\n order by count() desc\n    limit 100',
                        filters: {
                            dateRange: {
                                date_from: '-24h',
                            },
                        },
                    },
                },
                filters: {},
                description: '',
            },
        },
        {
            type: 'insight',
            result_id: 'zi5MCnjs',
            extra_fields: {
                name: 'Feature Flag Called Total Volume',
                query: null,
                filters: {
                    events: [
                        {
                            id: '$feature_flag_called',
                            name: '$feature_flag_called',
                            type: 'events',
                        },
                    ],
                    display: 'ActionsLineGraph',
                    insight: 'TRENDS',
                    interval: 'day',
                    breakdown: '$feature_flag_response',
                    date_from: '-30d',
                    properties: {
                        type: 'AND',
                        values: [
                            {
                                type: 'AND',
                                values: [
                                    {
                                        key: '$feature_flag',
                                        type: 'event',
                                        value: 'notebooks',
                                    },
                                ],
                            },
                        ],
                    },
                    breakdown_type: 'event',
                    filter_test_accounts: false,
                },
                description: 'Shows the number of total calls made on feature flag with key: notebooks',
            },
        },
        {
            type: 'feature_flag',
            result_id: '120',
            extra_fields: {
                key: 'person-on-events-enabled',
                name: 'person-on-events-enabled',
            },
        },
        {
            type: 'feature_flag',
            result_id: '150',
            extra_fields: {
                key: 'cs-dashboards',
                name: 'cs-dashboards',
            },
        },
        {
            type: 'notebook',
            result_id: 'b1ZyFO6K',
            extra_fields: {
                title: 'Notes 27/09',
                text_content: 'Notes 27/09\nasd\nas\nda\ns\nd\nlalala',
            },
        },
        {
            type: 'feature_flag',
            result_id: '143',
            extra_fields: {
                key: 'high-frequency-batch-exports',
                name: 'high-frequency-batch-exports',
            },
        },
        {
            type: 'feature_flag',
            result_id: '126',
            extra_fields: {
                key: 'onboarding-v2-demo',
                name: 'onboarding-v2-demo',
            },
        },
        {
            type: 'insight',
            result_id: 'miwdcAAu',
            extra_fields: {
                name: '',
                query: {
                    full: true,
                    kind: 'DataTableNode',
                    source: {
                        kind: 'HogQLQuery',
                        query: '   select event,\n          person.properties.email,\n          properties.$browser,\n          count()\n     from events\n    where {filters} -- replaced with global date and property filters\n      and person.properties.email is not null\n group by event,\n          properties.$browser,\n          person.properties.email\n order by count() desc\n    limit 100',
                        filters: {
                            dateRange: {
                                date_from: '-24h',
                            },
                        },
                    },
                },
                filters: {},
                description: '',
            },
        },
        {
            type: 'feature_flag',
            result_id: '142',
            extra_fields: {
                key: 'web-analytics',
                name: 'web-analytics',
            },
        },
        {
            type: 'notebook',
            result_id: 'eq4n8PQY',
            extra_fields: {
                title: 'asd',
                text_content: 'asd',
            },
        },
        {
            type: 'dashboard',
            result_id: '1',
            extra_fields: {
                name: '🔑 Key metrics',
                description: 'Company overview.',
            },
        },
        {
            type: 'insight',
            result_id: 'YZjAFWBU',
            extra_fields: {
                name: 'Homepage view to signup conversion',
                query: null,
                filters: {
                    events: [
                        {
                            id: '$pageview',
                            name: '$pageview',
                            type: 'events',
                            order: 0,
                            properties: [
                                {
                                    key: '$current_url',
                                    type: 'event',
                                    value: 'https://hedgebox.net/',
                                    operator: 'exact',
                                },
                            ],
                            custom_name: 'Viewed homepage',
                        },
                        {
                            id: '$pageview',
                            name: '$pageview',
                            type: 'events',
                            order: 1,
                            properties: [
                                {
                                    key: '$current_url',
                                    type: 'event',
                                    value: 'https://hedgebox.net/signup/',
                                    operator: 'regex',
                                },
                            ],
                            custom_name: 'Viewed signup page',
                        },
                        {
                            id: 'signed_up',
                            name: 'signed_up',
                            type: 'events',
                            order: 2,
                            custom_name: 'Signed up',
                        },
                    ],
                    actions: [],
                    display: 'FunnelViz',
                    insight: 'FUNNELS',
                    interval: 'day',
                    date_from: '-1m',
                    funnel_viz_type: 'steps',
                    filter_test_accounts: true,
                },
                description: null,
            },
        },
        {
            type: 'feature_flag',
            result_id: '133',
            extra_fields: {
                key: 'feedback-scene',
                name: 'feedback-scene',
            },
        },
        {
            type: 'insight',
            result_id: 'xK9vs4D2',
            extra_fields: {
                name: '',
                query: null,
                filters: {
                    events: [
                        {
                            id: '$pageview',
                            math: 'total',
                            name: '$pageview',
                            type: 'events',
                            order: 0,
                        },
                        {
                            id: null,
                            math: 'total',
                            type: 'events',
                            order: 1,
                        },
                        {
                            id: null,
                            math: 'total',
                            type: 'events',
                            order: 2,
                        },
                    ],
                    insight: 'FUNNELS',
                    interval: 'day',
                    date_from: '-7d',
                    exclusions: [
                        {
                            id: '$pageview',
                            name: '$pageview',
                            type: 'events',
                            uuid: '40e0f8a9-1297-41e4-b7ca-54d00a9c1d82',
                            order: 0,
                            funnel_to_step: 1,
                            funnel_from_step: 0,
                        },
                    ],
                    entity_type: 'events',
                    funnel_viz_type: 'steps',
                },
                description: '',
            },
        },
        {
            type: 'feature_flag',
            result_id: '161',
            extra_fields: {
                key: 'console-recording-search',
                name: 'console-recording-search',
            },
        },
        {
            type: 'feature_flag',
            result_id: '134',
            extra_fields: {
                key: 'early-access-feature',
                name: 'early-access-feature',
            },
        },
        {
            type: 'insight',
            result_id: 'vLbs5bhA',
            extra_fields: {
                name: '',
                query: null,
                filters: {
                    events: [
                        {
                            id: '$pageview',
                            math: 'total',
                            name: '$pageview',
                            type: 'events',
                            order: 0,
                        },
                    ],
                    insight: 'LIFECYCLE',
                    shown_as: 'Lifecycle',
                    entity_type: 'events',
                    filter_test_accounts: false,
                },
                description: '',
            },
        },
        {
            type: 'feature_flag',
            result_id: '159',
            extra_fields: {
                key: 'surveys-multiple-questions',
                name: 'surveys-multiple-questions',
            },
        },
        {
            type: 'action',
            result_id: '3',
            extra_fields: {
                name: 'typed into search',
                description: '',
            },
        },
        {
            type: 'insight',
            result_id: 'QYrl34sX',
            extra_fields: {
                name: 'Feature Flag calls made by unique users per variant',
                query: null,
                filters: {
                    events: [
                        {
                            id: '$feature_flag_called',
                            math: 'dau',
                            name: '$feature_flag_called',
                            type: 'events',
                        },
                    ],
                    display: 'ActionsTable',
                    insight: 'TRENDS',
                    interval: 'day',
                    breakdown: '$feature_flag_response',
                    date_from: '-30d',
                    properties: {
                        type: 'AND',
                        values: [
                            {
                                type: 'AND',
                                values: [
                                    {
                                        key: '$feature_flag',
                                        type: 'event',
                                        value: 'cmd-k-search',
                                    },
                                ],
                            },
                        ],
                    },
                    breakdown_type: 'event',
                    filter_test_accounts: false,
                },
                description:
                    'Shows the number of unique user calls made on feature flag per variant with key: cmd-k-search',
            },
        },
        {
            type: 'insight',
            result_id: '4Xaltnro',
            extra_fields: {
                name: '',
                query: null,
                filters: {
                    insight: 'PATHS',
                    step_limit: 5,
                    entity_type: 'events',
                    funnel_paths: 'funnel_path_before_step',
                    funnel_filter: {
                        events: [
                            {
                                id: '$pageview',
                                math: 'total',
                                name: '$pageview',
                                type: 'events',
                                order: 0,
                            },
                            {
                                id: null,
                                math: 'total',
                                type: 'events',
                                order: 1,
                            },
                        ],
                        insight: 'FUNNELS',
                        exclusions: [],
                        funnel_step: 2,
                        funnel_viz_type: 'steps',
                        filter_test_accounts: true,
                    },
                    include_event_types: ['$pageview', 'custom_event'],
                },
                description: '',
            },
        },
        {
            type: 'feature_flag',
            result_id: '148',
            extra_fields: {
                key: 'show-product-intro-existing-products',
                name: 'show-product-intro-existing-products',
            },
        },
        {
            type: 'feature_flag',
            result_id: '4',
            extra_fields: {
                key: 'notebooks',
                name: '',
            },
        },
    ],
    counts: {
        insight: 89,
        dashboard: 14,
        experiment: 1,
        feature_flag: 66,
        notebook: 5,
        action: 4,
        cohort: 3,
    },
}

const meta: Meta<typeof CommandBar> = {
    title: 'Components/Command Bar',
    component: CommandBar,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/search': SEARCH_RESULT,
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            snapshotTargetSelector: '[data-attr="command-bar"]',
            include3000: true,
        },
        viewMode: 'story',
    },
}
export default meta

export function Search(): JSX.Element {
    const { setCommandBar } = useActions(commandBarLogic)

    useEffect(() => {
        setCommandBar(BarStatus.SHOW_SEARCH)
    }, [])

    return <CommandBar />
}

export function Actions(): JSX.Element {
    const { setCommandBar } = useActions(commandBarLogic)

    useEffect(() => {
        setCommandBar(BarStatus.SHOW_ACTIONS)
    }, [])

    return <CommandBar />
}

export function Shortcuts(): JSX.Element {
    const { setCommandBar } = useActions(commandBarLogic)

    useEffect(() => {
        setCommandBar(BarStatus.SHOW_SHORTCUTS)
    }, [])

    return <CommandBar />
}
