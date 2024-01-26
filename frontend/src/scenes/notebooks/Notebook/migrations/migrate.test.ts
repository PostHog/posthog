import { NotebookType } from '~/types'

import mockNotebook from '../__mocks__/notebook-12345.json'
import { JSONContent } from '../utils'
import { migrate } from './migrate'

describe('migrate()', () => {
    const contentToExpected: [string, JSONContent[], JSONContent[]][] = [
        ['migrates node without changes', [{ type: 'paragraph' }], [{ type: 'paragraph' }]],
        [
            'migrates query node with string content to object content',
            [
                {
                    type: 'ph-query',
                    attrs: {
                        query: '{"kind":"InsightVizNode","source":{"kind":"TrendsQuery","properties":{"type":"AND","values":[{"type":"AND","values":[]}]},"filterTestAccounts":true,"dateRange":{"date_to":null,"date_from":"-90d"},"series":[{"kind":"EventsNode","event":"$pageview","name":"$pageview","properties":[{"key":"$referring_domain","type":"event","value":"google|duckduckgo|brave|bing","operator":"regex"},{"key":"utm_source","type":"event","value":"is_not_set","operator":"is_not_set"},{"key":"$host","type":"event","value":["posthog.com"],"operator":"exact"}],"math":"dau"}],"interval":"week","breakdown":{"breakdown_type":"event","breakdown":"$referring_domain"},"trendsFilter":{"compare":false,"display":"ActionsBar"}}}',
                        title: 'SEO trend last 90 days',
                        __init: null,
                        height: null,
                        nodeId: '245516ed-8bb2-41c3-83c6-fc10bb0c5149',
                        children: null,
                    },
                },
            ],
            [
                {
                    type: 'ph-query',
                    attrs: {
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'TrendsQuery',
                                properties: { type: 'AND', values: [{ type: 'AND', values: [] }] },
                                filterTestAccounts: true,
                                dateRange: { date_to: null, date_from: '-90d' },
                                series: [
                                    {
                                        kind: 'EventsNode',
                                        event: '$pageview',
                                        name: '$pageview',
                                        properties: [
                                            {
                                                key: '$referring_domain',
                                                type: 'event',
                                                value: 'google|duckduckgo|brave|bing',
                                                operator: 'regex',
                                            },
                                            {
                                                key: 'utm_source',
                                                type: 'event',
                                                value: 'is_not_set',
                                                operator: 'is_not_set',
                                            },
                                            { key: '$host', type: 'event', value: ['posthog.com'], operator: 'exact' },
                                        ],
                                        math: 'dau',
                                    },
                                ],
                                interval: 'week',
                                breakdownFilter: { breakdown_type: 'event', breakdown: '$referring_domain' },
                                trendsFilter: { compare: false, display: 'ActionsBar' },
                            },
                        },
                        title: 'SEO trend last 90 days',
                        __init: null,
                        height: null,
                        nodeId: '245516ed-8bb2-41c3-83c6-fc10bb0c5149',
                        children: null,
                    },
                },
            ],
        ],
        [
            'migrates funnels filter',
            [
                {
                    type: 'ph-query',
                    attrs: {
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'FunnelsQuery',
                                series: [
                                    {
                                        kind: 'EventsNode',
                                        math: 'total',
                                        name: 'user signed up',
                                        event: 'user signed up',
                                        properties: [
                                            {
                                                key: 'is_organization_first_user',
                                                type: 'person',
                                                value: ['true'],
                                                operator: 'exact',
                                            },
                                            {
                                                key: 'realm',
                                                type: 'event',
                                                value: ['cloud'],
                                                operator: 'exact',
                                            },
                                        ],
                                    },
                                    {
                                        kind: 'EventsNode',
                                        math: 'total',
                                        name: 'recording analyzed',
                                        event: 'recording analyzed',
                                    },
                                ],
                                interval: 'day',
                                dateRange: { date_to: '', date_from: '-6w' },
                                funnelsFilter: {
                                    funnel_viz_type: 'trends',
                                    funnel_order_type: 'ordered',
                                    funnel_window_interval: 14,
                                    funnel_window_interval_unit: 'day',
                                },
                                aggregation_group_type_index: 0,
                            },
                        },
                        title: 'Organisation signed up -> recording analyzed, last 6 weeks',
                        __init: null,
                        height: 516,
                        nodeId: 'be5c5e34-f330-4f3f-9a2f-6361c60d0f2e',
                        children: null,
                    },
                },
            ],
            [
                {
                    type: 'ph-query',
                    attrs: {
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'FunnelsQuery',
                                series: [
                                    {
                                        kind: 'EventsNode',
                                        math: 'total',
                                        name: 'user signed up',
                                        event: 'user signed up',
                                        properties: [
                                            {
                                                key: 'is_organization_first_user',
                                                type: 'person',
                                                value: ['true'],
                                                operator: 'exact',
                                            },
                                            {
                                                key: 'realm',
                                                type: 'event',
                                                value: ['cloud'],
                                                operator: 'exact',
                                            },
                                        ],
                                    },
                                    {
                                        kind: 'EventsNode',
                                        math: 'total',
                                        name: 'recording analyzed',
                                        event: 'recording analyzed',
                                    },
                                ],
                                interval: 'day',
                                dateRange: { date_to: '', date_from: '-6w' },
                                funnelsFilter: {
                                    funnelOrderType: 'ordered',
                                    funnelVizType: 'trends',
                                    funnelWindowInterval: 14,
                                    funnelWindowIntervalUnit: 'day',
                                },
                                aggregation_group_type_index: 0,
                            },
                        },
                        title: 'Organisation signed up -> recording analyzed, last 6 weeks',
                        __init: null,
                        height: 516,
                        nodeId: 'be5c5e34-f330-4f3f-9a2f-6361c60d0f2e',
                        children: null,
                    },
                },
            ],
        ],
        [
            'migrates retention filter',
            [
                {
                    type: 'ph-query',
                    attrs: {
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'RetentionQuery',
                                retentionFilter: {
                                    period: 'Week',
                                    targetEntity: {
                                        id: 'recording analyzed',
                                        name: 'recording analyzed',
                                        type: 'events',
                                        uuid: 'ae1136ce-cee1-4225-b27a-fbff3a99d4a9',
                                        order: 0,
                                    },
                                    retentionType: 'retention_first_time',
                                    target_entity: {
                                        id: 'recording analyzed',
                                        name: 'recording analyzed',
                                        type: 'events',
                                        uuid: 'af560c55-fa85-4c38-b056-94b6e253530a',
                                        order: 0,
                                    },
                                    retention_type: 'retention_first_time',
                                    total_intervals: 7,
                                    returning_entity: {
                                        id: 'recording analyzed',
                                        name: 'recording analyzed',
                                        type: 'events',
                                        uuid: '286575a9-1485-47d0-9bf6-9d439bc051b3',
                                        order: 0,
                                    },
                                    retention_reference: 'total',
                                },
                                aggregation_group_type_index: 0,
                            },
                        },
                        title: "Retention 'recording analyzed' for unique organizations, last 6 weeks",
                        __init: null,
                        height: null,
                        nodeId: 'a562d7e0-068f-40c3-ac1b-ca91f1d5effe',
                        children: null,
                    },
                },
            ],
            [
                {
                    type: 'ph-query',
                    attrs: {
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'RetentionQuery',
                                retentionFilter: {
                                    period: 'Week',
                                    targetEntity: {
                                        id: 'recording analyzed',
                                        name: 'recording analyzed',
                                        type: 'events',
                                        uuid: 'af560c55-fa85-4c38-b056-94b6e253530a',
                                        order: 0,
                                    },
                                    retentionType: 'retention_first_time',
                                    totalIntervals: 7,
                                    returningEntity: {
                                        id: 'recording analyzed',
                                        name: 'recording analyzed',
                                        type: 'events',
                                        uuid: '286575a9-1485-47d0-9bf6-9d439bc051b3',
                                        order: 0,
                                    },
                                    retentionReference: 'total',
                                },
                                aggregation_group_type_index: 0,
                            },
                        },
                        title: "Retention 'recording analyzed' for unique organizations, last 6 weeks",
                        __init: null,
                        height: null,
                        nodeId: 'a562d7e0-068f-40c3-ac1b-ca91f1d5effe',
                        children: null,
                    },
                },
            ],
        ],
        [
            'migrates trends queries (mixed with breakdown)',
            [
                {
                    type: 'ph-query',
                    attrs: {
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'TrendsQuery',
                                series: [
                                    {
                                        kind: 'EventsNode',
                                        math: 'dau',
                                        name: '$pageview',
                                        event: '$pageview',
                                        properties: [
                                            {
                                                key: '$current_url',
                                                type: 'event',
                                                value: 'https://(app|eu).posthog.com',
                                                operator: 'regex',
                                            },
                                        ],
                                    },
                                ],
                                interval: 'day',
                                breakdown: {
                                    breakdown: '$feature/posthog-3000',
                                    breakdown_type: 'event',
                                },
                                trendsFilter: {
                                    display: 'ActionsLineGraph',
                                    show_legend: true,
                                },
                                filterTestAccounts: false,
                            },
                        },
                        title: 'Rollout of users on 3000',
                        __init: null,
                        height: null,
                        nodeId: '4c2a07ee-fc9f-45c5-b36c-5e14a10f8e89',
                        children: null,
                    },
                },
            ],
            [
                {
                    type: 'ph-query',
                    attrs: {
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'TrendsQuery',
                                series: [
                                    {
                                        kind: 'EventsNode',
                                        math: 'dau',
                                        name: '$pageview',
                                        event: '$pageview',
                                        properties: [
                                            {
                                                key: '$current_url',
                                                type: 'event',
                                                value: 'https://(app|eu).posthog.com',
                                                operator: 'regex',
                                            },
                                        ],
                                    },
                                ],
                                interval: 'day',
                                breakdownFilter: {
                                    breakdown: '$feature/posthog-3000',
                                    breakdown_type: 'event',
                                },
                                trendsFilter: {
                                    display: 'ActionsLineGraph',
                                    showLegend: true,
                                },
                                filterTestAccounts: false,
                            },
                        },
                        title: 'Rollout of users on 3000',
                        __init: null,
                        height: null,
                        nodeId: '4c2a07ee-fc9f-45c5-b36c-5e14a10f8e89',
                        children: null,
                    },
                },
            ],
        ],
        [
            'migrates breakdown',
            [
                {
                    type: 'ph-query',
                    attrs: {
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'TrendsQuery',
                                series: [
                                    {
                                        kind: 'EventsNode',
                                        math: 'dau',
                                        name: '$pageview',
                                        event: '$pageview',
                                        properties: [
                                            {
                                                key: '$referring_domain',
                                                type: 'event',
                                                value: 'google|duckduckgo|brave|bing',
                                                operator: 'regex',
                                            },
                                            {
                                                key: 'utm_source',
                                                type: 'event',
                                                value: 'is_not_set',
                                                operator: 'is_not_set',
                                            },
                                            {
                                                key: '$host',
                                                type: 'event',
                                                value: ['posthog.com'],
                                                operator: 'exact',
                                            },
                                        ],
                                    },
                                ],
                                interval: 'week',
                                breakdown: {
                                    breakdown: '$referring_domain',
                                    breakdown_type: 'event',
                                },
                                dateRange: { date_to: null, date_from: '-90d' },
                                properties: {
                                    type: 'AND',
                                    values: [{ type: 'AND', values: [] }],
                                },
                                trendsFilter: { compare: false, display: 'ActionsBar' },
                                filterTestAccounts: true,
                            },
                        },
                        title: 'SEO trend last 90 days',
                        __init: null,
                        height: null,
                        nodeId: '245516ed-8bb2-41c3-83c6-fc10bb0c5149',
                        children: null,
                    },
                },
            ],
            [
                {
                    type: 'ph-query',
                    attrs: {
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'TrendsQuery',
                                series: [
                                    {
                                        kind: 'EventsNode',
                                        math: 'dau',
                                        name: '$pageview',
                                        event: '$pageview',
                                        properties: [
                                            {
                                                key: '$referring_domain',
                                                type: 'event',
                                                value: 'google|duckduckgo|brave|bing',
                                                operator: 'regex',
                                            },
                                            {
                                                key: 'utm_source',
                                                type: 'event',
                                                value: 'is_not_set',
                                                operator: 'is_not_set',
                                            },
                                            {
                                                key: '$host',
                                                type: 'event',
                                                value: ['posthog.com'],
                                                operator: 'exact',
                                            },
                                        ],
                                    },
                                ],
                                interval: 'week',
                                breakdownFilter: {
                                    breakdown: '$referring_domain',
                                    breakdown_type: 'event',
                                },
                                dateRange: { date_to: null, date_from: '-90d' },
                                properties: {
                                    type: 'AND',
                                    values: [{ type: 'AND', values: [] }],
                                },
                                trendsFilter: { compare: false, display: 'ActionsBar' },
                                filterTestAccounts: true,
                            },
                        },
                        title: 'SEO trend last 90 days',
                        __init: null,
                        height: null,
                        nodeId: '245516ed-8bb2-41c3-83c6-fc10bb0c5149',
                        children: null,
                    },
                },
            ],
        ],
        [
            'migrates paths filter',
            [
                {
                    type: 'ph-query',
                    attrs: {
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'PathsQuery',
                                interval: 'day',
                                dateRange: { date_to: null, date_from: '-30d' },
                                pathsFilter: {
                                    edge_limit: 20,
                                    step_limit: 9,
                                    start_point: 'https://posthog.com/blog/best-mixpanel-alternatives',
                                    include_event_types: ['$pageview'],
                                },
                                filterTestAccounts: true,
                            },
                        },
                        title: null,
                        __init: null,
                        height: null,
                        nodeId: 'e2f225af-7e5f-40c0-afbd-832cbb866079',
                        children: null,
                    },
                },
            ],
            [
                {
                    type: 'ph-query',
                    attrs: {
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'PathsQuery',
                                interval: 'day',
                                dateRange: { date_to: null, date_from: '-30d' },
                                pathsFilter: {
                                    edgeLimit: 20,
                                    stepLimit: 9,
                                    startPoint: 'https://posthog.com/blog/best-mixpanel-alternatives',
                                    includeEventTypes: ['$pageview'],
                                },
                                filterTestAccounts: true,
                            },
                        },
                        title: null,
                        __init: null,
                        height: null,
                        nodeId: 'e2f225af-7e5f-40c0-afbd-832cbb866079',
                        children: null,
                    },
                },
            ],
        ],
        [
            'migrates series TODO',
            [
                {
                    type: 'ph-query',
                    attrs: {
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'TrendsQuery',
                                series: [
                                    {
                                        id: '2674',
                                        kind: 'ActionsNode',
                                        math: 'unique_group',
                                        name: 'User Signed Up (Comprehensive)',
                                        properties: [
                                            {
                                                key: 'is_organization_first_user',
                                                type: 'event',
                                                value: ['true'],
                                                operator: 'exact',
                                            },
                                        ],
                                        custom_name: 'All Org Signups',
                                        math_group_type_index: 0,
                                    },
                                    {
                                        id: '2674',
                                        kind: 'ActionsNode',
                                        math: 'unique_group',
                                        name: 'User Signed Up (Comprehensive)',
                                        properties: [
                                            {
                                                key: 'id',
                                                type: 'cohort',
                                                value: 15394,
                                                operator: null,
                                            },
                                            {
                                                key: 'is_organization_first_user',
                                                type: 'event',
                                                value: ['true'],
                                                operator: 'exact',
                                            },
                                        ],
                                        custom_name: 'High ICP Organizations',
                                        math_group_type_index: 0,
                                    },
                                    {
                                        id: '8231',
                                        kind: 'ActionsNode',
                                        math: 'unique_group',
                                        name: 'User Signed Up (Cloud)',
                                        properties: [
                                            {
                                                key: 'is_organization_first_user',
                                                type: 'event',
                                                value: ['true'],
                                                operator: 'exact',
                                            },
                                        ],
                                        custom_name: 'Cloud Signups',
                                        math_group_type_index: 0,
                                    },
                                    {
                                        id: '9847',
                                        kind: 'ActionsNode',
                                        math: 'unique_group',
                                        name: 'User signed up (self-hosted Clickhouse)',
                                        properties: [
                                            {
                                                key: 'is_organization_first_user',
                                                type: 'event',
                                                value: ['true'],
                                                operator: 'exact',
                                            },
                                        ],
                                        custom_name: 'Open Source Signups',
                                        math_group_type_index: 0,
                                    },
                                ],
                                interval: 'week',
                                dateRange: { date_to: null, date_from: '-90d' },
                                properties: {
                                    type: 'AND',
                                    values: [
                                        {
                                            type: 'AND',
                                            values: [
                                                {
                                                    key: 'email',
                                                    type: 'event',
                                                    value: 'posthog.com',
                                                    operator: 'not_icontains',
                                                },
                                                {
                                                    key: 'organization_name',
                                                    type: 'group',
                                                    value: ['teste'],
                                                    operator: 'is_not',
                                                    group_type_index: 0,
                                                },
                                                {
                                                    key: 'organization_name',
                                                    type: 'group',
                                                    value: ['HOgflix movie'],
                                                    operator: 'is_not',
                                                    group_type_index: 0,
                                                },
                                            ],
                                        },
                                    ],
                                },
                                trendsFilter: {
                                    compare: false,
                                    display: 'ActionsLineGraph',
                                    show_legend: false,
                                    smoothing_intervals: 1,
                                    show_values_on_series: true,
                                },
                                filterTestAccounts: false,
                            },
                        },
                        title: 'Weekly Org Signups',
                        __init: null,
                        height: null,
                        nodeId: '564e15f2-78a0-4ff9-837d-c871aa71c2ef',
                        children: null,
                    },
                },
            ],
            [
                {
                    type: 'ph-query',
                    attrs: {
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'TrendsQuery',
                                series: [
                                    {
                                        id: '2674',
                                        kind: 'ActionsNode',
                                        math: 'unique_group',
                                        name: 'User Signed Up (Comprehensive)',
                                        properties: [
                                            {
                                                key: 'is_organization_first_user',
                                                type: 'event',
                                                value: ['true'],
                                                operator: 'exact',
                                            },
                                        ],
                                        custom_name: 'All Org Signups',
                                        math_group_type_index: 0,
                                    },
                                    {
                                        id: '2674',
                                        kind: 'ActionsNode',
                                        math: 'unique_group',
                                        name: 'User Signed Up (Comprehensive)',
                                        properties: [
                                            {
                                                key: 'id',
                                                type: 'cohort',
                                                value: 15394,
                                                operator: null,
                                            },
                                            {
                                                key: 'is_organization_first_user',
                                                type: 'event',
                                                value: ['true'],
                                                operator: 'exact',
                                            },
                                        ],
                                        custom_name: 'High ICP Organizations',
                                        math_group_type_index: 0,
                                    },
                                    {
                                        id: '8231',
                                        kind: 'ActionsNode',
                                        math: 'unique_group',
                                        name: 'User Signed Up (Cloud)',
                                        properties: [
                                            {
                                                key: 'is_organization_first_user',
                                                type: 'event',
                                                value: ['true'],
                                                operator: 'exact',
                                            },
                                        ],
                                        custom_name: 'Cloud Signups',
                                        math_group_type_index: 0,
                                    },
                                    {
                                        id: '9847',
                                        kind: 'ActionsNode',
                                        math: 'unique_group',
                                        name: 'User signed up (self-hosted Clickhouse)',
                                        properties: [
                                            {
                                                key: 'is_organization_first_user',
                                                type: 'event',
                                                value: ['true'],
                                                operator: 'exact',
                                            },
                                        ],
                                        custom_name: 'Open Source Signups',
                                        math_group_type_index: 0,
                                    },
                                ],
                                interval: 'week',
                                dateRange: { date_to: null, date_from: '-90d' },
                                properties: {
                                    type: 'AND',
                                    values: [
                                        {
                                            type: 'AND',
                                            values: [
                                                {
                                                    key: 'email',
                                                    type: 'event',
                                                    value: 'posthog.com',
                                                    operator: 'not_icontains',
                                                },
                                                {
                                                    key: 'organization_name',
                                                    type: 'group',
                                                    value: ['teste'],
                                                    operator: 'is_not',
                                                    group_type_index: 0,
                                                },
                                                {
                                                    key: 'organization_name',
                                                    type: 'group',
                                                    value: ['HOgflix movie'],
                                                    operator: 'is_not',
                                                    group_type_index: 0,
                                                },
                                            ],
                                        },
                                    ],
                                },
                                trendsFilter: {
                                    compare: false,
                                    display: 'ActionsLineGraph',
                                    showLegend: false,
                                    smoothingIntervals: 1,
                                    showValuesOnSeries: true,
                                },
                                filterTestAccounts: false,
                            },
                        },
                        title: 'Weekly Org Signups',
                        __init: null,
                        height: null,
                        nodeId: '564e15f2-78a0-4ff9-837d-c871aa71c2ef',
                        children: null,
                    },
                },
            ],
        ],
    ]

    contentToExpected.forEach(([name, prevContent, nextContent]) => {
        it(name, () => {
            const prevNotebook: NotebookType = {
                ...mockNotebook,
                content: { type: 'doc', content: prevContent },
            }
            const nextNotebook: NotebookType = {
                ...mockNotebook,
                content: { type: 'doc', content: nextContent },
            }

            expect(migrate(prevNotebook)).toEqual(nextNotebook)
        })
    })
})
