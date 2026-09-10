import { JSONContent } from 'lib/components/RichContentEditor/types'
import { NotebookType } from 'scenes/notebooks/types'

import { useMocks } from '~/mocks/jest'
import { LATEST_VERSIONS } from '~/queries/latest-versions'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import mockNotebook from '../__mocks__/notebook-12345.json'
import { migrate } from './migrate'

describe('migrate()', () => {
    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/upgrade': async ({ request }) => {
                    const data = (await request.json()) as any
                    const kind = data?.query?.source?.kind
                    // These fixtures have no result customizations and fully tagged series, so
                    // the backend migrations are a no-op beyond the version bump they apply.
                    if (
                        kind === 'TrendsQuery' ||
                        kind === 'StickinessQuery' ||
                        kind === 'FunnelsQuery' ||
                        kind === 'LifecycleQuery' ||
                        kind === 'CalendarHeatmapQuery'
                    ) {
                        return [
                            200,
                            {
                                query: {
                                    ...data.query,
                                    source: { ...data.query.source, version: LATEST_VERSIONS[kind as NodeKind] },
                                },
                            },
                        ]
                    }
                    if (kind === 'RetentionQuery') {
                        return [
                            200,
                            {
                                query: {
                                    kind: 'InsightVizNode',
                                    source: {
                                        version: 2,
                                        aggregation_group_type_index: 0,
                                        kind: 'RetentionQuery',
                                        retentionFilter: {
                                            meanRetentionCalculation: 'simple',
                                            period: 'Week',
                                            retentionReference: 'total',
                                            retentionType: 'retention_first_time',
                                            returningEntity: {
                                                id: 'recording analyzed',
                                                name: 'recording analyzed',
                                                order: 0,
                                                type: 'events',
                                                uuid: '286575a9-1485-47d0-9bf6-9d439bc051b3',
                                            },
                                            targetEntity: {
                                                id: 'recording analyzed',
                                                name: 'recording analyzed',
                                                order: 0,
                                                type: 'events',
                                                uuid: 'af560c55-fa85-4c38-b056-94b6e253530a',
                                            },
                                            totalIntervals: 7,
                                        },
                                    },
                                },
                            },
                        ]
                    }
                    return [500, {}]
                },
            },
        })

        initKeaTests()
    })

    const contentToExpected: [string, JSONContent[], JSONContent[]][] = [
        ['migrates node without changes', [{ type: 'paragraph' }], [{ type: 'paragraph' }]],
        [
            'recovers a flattened markdown table from a literal paragraph',
            [{ type: 'paragraph', content: [{ type: 'text', text: '| a | b | |---|---| | 1 | 2 |' }] }],
            [
                {
                    type: 'table',
                    content: [
                        {
                            type: 'tableRow',
                            content: [
                                {
                                    type: 'tableHeader',
                                    content: [{ type: 'paragraph', content: [{ type: 'text', text: 'a' }] }],
                                },
                                {
                                    type: 'tableHeader',
                                    content: [{ type: 'paragraph', content: [{ type: 'text', text: 'b' }] }],
                                },
                            ],
                        },
                        {
                            type: 'tableRow',
                            content: [
                                {
                                    type: 'tableCell',
                                    content: [{ type: 'paragraph', content: [{ type: 'text', text: '1' }] }],
                                },
                                {
                                    type: 'tableCell',
                                    content: [{ type: 'paragraph', content: [{ type: 'text', text: '2' }] }],
                                },
                            ],
                        },
                    ],
                },
            ],
        ],
        [
            'migrates query node with string content to object content',
            [
                {
                    type: 'ph-query',
                    attrs: {
                        query: '{"kind":"InsightVizNode","source":{"kind":"TrendsQuery","properties":{"type":"AND","values":[{"type":"AND","values":[]}]},"filterTestAccounts":true,"dateRange":{"date_to":null,"date_from":"-90d"},"series":[{"kind":"EventsNode","event":"$pageview","name":"$pageview","properties":[{"key":"$referring_domain","type":"event","value":"google|duckduckgo|brave|bing","operator":"regex"},{"key":"utm_source","type":"event","value":"is_not_set","operator":"is_not_set"},{"key":"$host","type":"event","value":["posthog.com"],"operator":"exact"}],"math":"dau"}],"interval":"week","breakdown":{"breakdown_type":"event","breakdown":"$referring_domain"},"trendsFilter":{"compare":true,"display":"ActionsBar"},"version":2}}',
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
                                trendsFilter: { compare: true, display: 'ActionsBar' },
                                version: LATEST_VERSIONS[NodeKind.TrendsQuery],
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
                                version: 2,
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
                                    meanRetentionCalculation: 'simple',
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
    ]

    it.each(contentToExpected)('migrates %s', async (_name, prevContent, nextContent) => {
        const prevNotebook: NotebookType = {
            ...mockNotebook,
            user_access_level: AccessControlLevel.Editor,
            content: { type: 'doc', content: prevContent },
        }
        const nextNotebook: NotebookType = {
            ...mockNotebook,
            user_access_level: AccessControlLevel.Editor,
            content: { type: 'doc', content: nextContent },
        }

        await expect(migrate(prevNotebook)).resolves.toEqual(nextNotebook)
    })
})
