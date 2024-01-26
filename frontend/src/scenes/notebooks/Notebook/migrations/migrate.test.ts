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
                                breakdown: { breakdown_type: 'event', breakdown: '$referring_domain' },
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
