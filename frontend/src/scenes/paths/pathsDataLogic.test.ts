import { expectLogic } from 'kea-test-utils'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { buildFunnelEventsFromPathNode, buildPaths, pathsDataLogic } from 'scenes/paths/pathsDataLogic'
import { teamLogic } from 'scenes/teamLogic'

import { examples } from '~/queries/examples'
import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps, PathType, PropertyFilterType, PropertyOperator } from '~/types'

import { PathNodeData, PathTargetLink } from './pathUtils'

let logic: ReturnType<typeof pathsDataLogic.build>

const insightProps: InsightLogicProps = {
    dashboardItemId: undefined,
    cachedInsight: {
        query: { kind: NodeKind.InsightVizNode, source: examples.InsightPathsQuery } as InsightVizNode,
    },
}

async function initPathsDataLogic(): Promise<void> {
    logic = pathsDataLogic(insightProps)
    logic.mount()
    await expectLogic(logic).toFinishAllListeners()
}

describe('pathsDataLogic', () => {
    beforeEach(async () => {
        initKeaTests(false)
        teamLogic.mount()
        await initPathsDataLogic()
    })

    it('selects taxonomicGroupTypes from pathsFilter', async () => {
        await expectLogic(logic, () => {
            logic.actions.updateInsightFilter({
                includeEventTypes: [PathType.PageView, PathType.Screen, PathType.CustomEvent],
            })
        })
            .toFinishAllListeners()
            .toMatchValues(logic, {
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.PageviewUrls,
                    TaxonomicFilterGroupType.Screens,
                    TaxonomicFilterGroupType.CustomEvents,
                    TaxonomicFilterGroupType.Wildcards,
                ],
            })
    })
})

describe('buildPaths', () => {
    it('builds nodes and links from valid paths links', () => {
        const results = [
            { source: '1_a', target: '2_b', value: 5, average_conversion_time: 10 },
            { source: '2_b', target: '3_c', value: 3, average_conversion_time: 20 },
        ]

        expect(buildPaths(results)).toEqual({
            nodes: [{ name: '1_a' }, { name: '2_b' }, { name: '3_c' }],
            links: results,
        })
    })

    // A stale result array from another query type can reach this selector paired with a paths
    // query. Such a row has no string source/target, and letting it through builds an undefined
    // node that later throws in renderPaths and blanks the whole insight scene.
    it('drops rows without string source and target', () => {
        const valid = { source: '1_a', target: '2_b', value: 5, average_conversion_time: 10 }
        const results = [valid, { value: 7 }, { source: 1, target: 2 }] as any

        expect(buildPaths(results)).toEqual({
            nodes: [{ name: '1_a' }, { name: '2_b' }],
            links: [valid],
        })
    })

    it('returns empty nodes when nothing is renderable', () => {
        expect(buildPaths([{ value: 7 }] as any)).toEqual({ nodes: [], links: [] })
    })
})

const makeNode = (name: string, depth: number, parent?: PathNodeData): PathNodeData =>
    ({
        name,
        depth,
        targetLinks: parent ? [{ source: parent } as PathTargetLink] : [],
    }) as PathNodeData

describe('buildFunnelEventsFromPathNode', () => {
    it.each([
        {
            scenario: 'custom event',
            node: makeNode('1_signed_up', 0),
            expected: [{ id: 'signed_up', name: 'signed_up', type: 'events', order: 0 }],
        },
        {
            scenario: 'URL node adds $pageview with $current_url property',
            node: makeNode('1_https://example.com/page', 0),
            expected: [
                {
                    id: '$pageview',
                    name: '$pageview',
                    type: 'events',
                    order: 0,
                    properties: [
                        {
                            key: '$current_url',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                            value: 'https://example.com/page',
                        },
                    ],
                },
            ],
        },
        {
            scenario: 'relative path',
            node: makeNode('1_/dashboard', 0),
            expected: [{ id: '/dashboard', name: '/dashboard', type: 'events', order: 0 }],
        },
        {
            scenario: 'screen name',
            node: makeNode('1_$screen', 0),
            expected: [{ id: '$screen', name: '$screen', type: 'events', order: 0 }],
        },
        {
            scenario: 'chain of mixed nodes walks backward via targetLinks',
            node: (() => {
                const start = makeNode('1_https://example.com/', 0)
                return makeNode('2_signed_up', 1, start)
            })(),
            expected: [
                { id: 'signed_up', name: 'signed_up', type: 'events', order: 1 },
                {
                    id: '$pageview',
                    name: '$pageview',
                    type: 'events',
                    order: 0,
                    properties: [
                        {
                            key: '$current_url',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                            value: 'https://example.com/',
                        },
                    ],
                },
            ],
        },
    ])('$scenario', ({ node, expected }) => {
        expect(buildFunnelEventsFromPathNode(node)).toEqual(expected)
    })
})
