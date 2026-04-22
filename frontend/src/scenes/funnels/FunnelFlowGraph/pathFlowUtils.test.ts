import { FunnelsQuery, NodeKind, PathsLink } from '~/queries/schema/schema-general'
import { FunnelPathType } from '~/types'

import {
    bridgeConfigForExpansion,
    buildPathFlowElements,
    buildPathsQuery,
    PathExpansion,
    pathExpansionCacheKey,
    PATH_NODE_HEIGHT,
    PATH_NODE_WIDTH,
} from './pathFlowUtils'

const SAMPLE_LINKS: PathsLink[] = [
    { source: '1_/home', target: '2_/pricing', value: 50, average_conversion_time: 30000 },
    { source: '1_/home', target: '2_/docs', value: 30, average_conversion_time: 25000 },
    { source: '2_/pricing', target: '3_/signup', value: 20, average_conversion_time: 45000 },
    { source: '2_/docs', target: '3_/signup', value: 10, average_conversion_time: 60000 },
]

describe('buildPathFlowElements', () => {
    it('returns empty elements for empty links', () => {
        const result = buildPathFlowElements([], 'step-0', 'step-1')
        expect(result.nodes).toEqual([])
        expect(result.edges).toEqual([])
    })

    it('creates path nodes from links with correct dimensions', () => {
        const { nodes } = buildPathFlowElements(SAMPLE_LINKS, 'step-0', 'step-1')

        expect(nodes).toHaveLength(4)
        for (const node of nodes) {
            expect(node.type).toBe('pathNode')
            expect(node.width).toBe(PATH_NODE_WIDTH)
            expect(node.height).toBe(PATH_NODE_HEIGHT)
            expect(node.draggable).toBe(false)
            expect(node.connectable).toBe(false)
        }
    })

    it('strips step prefix from event names', () => {
        const { nodes } = buildPathFlowElements(SAMPLE_LINKS, 'step-0', 'step-1')

        const eventNames = nodes.map((n) => n.data.eventName).sort()
        expect(eventNames).toEqual(['/docs', '/home', '/pricing', '/signup'])
    })

    it('assigns node IDs with path- prefix', () => {
        const { nodes } = buildPathFlowElements(SAMPLE_LINKS, 'step-0', 'step-1')

        const nodeIds = nodes.map((n) => n.id).sort()
        expect(nodeIds).toEqual(['path-1_/home', 'path-2_/docs', 'path-2_/pricing', 'path-3_/signup'])
    })

    it('creates edges between path nodes', () => {
        const { edges } = buildPathFlowElements(SAMPLE_LINKS, 'step-0', 'step-1')

        const pathEdges = edges.filter((e) => e.id.startsWith('path-edge-'))
        expect(pathEdges).toHaveLength(4)
    })

    it('creates bridge edges from source funnel step to first-layer path nodes', () => {
        const { edges } = buildPathFlowElements(SAMPLE_LINKS, 'step-0', 'step-1')

        const bridgesFrom = edges.filter((e) => e.id.startsWith('bridge-from-'))
        expect(bridgesFrom).toHaveLength(1)
        expect(bridgesFrom[0].source).toBe('step-0')
        expect(bridgesFrom[0].target).toBe('path-1_/home')
    })

    it('creates bridge edges from last-layer path nodes to target funnel step', () => {
        const { edges } = buildPathFlowElements(SAMPLE_LINKS, 'step-0', 'step-1')

        const bridgesTo = edges.filter((e) => e.id.startsWith('bridge-to-'))
        expect(bridgesTo).toHaveLength(1)
        expect(bridgesTo[0].source).toBe('path-3_/signup')
        expect(bridgesTo[0].target).toBe('step-1')
    })

    it('sets maxValue on edge data for stroke width scaling', () => {
        const { edges } = buildPathFlowElements(SAMPLE_LINKS, 'step-0', 'step-1')

        for (const edge of edges) {
            expect(edge.data?.maxValue).toBe(50)
        }
    })

    it('tracks count as max value across all links referencing the node', () => {
        const { nodes } = buildPathFlowElements(SAMPLE_LINKS, 'step-0', 'step-1')

        const homeNode = nodes.find((n) => n.id === 'path-1_/home')
        expect(homeNode?.data.count).toBe(50)

        const signupNode = nodes.find((n) => n.id === 'path-3_/signup')
        expect(signupNode?.data.count).toBe(20)
    })

    it('truncates long URL display names', () => {
        const longUrlLinks: PathsLink[] = [
            {
                source: '1_https://example.com/very/long/path/to/some/page',
                target: '2_https://example.com/another/very/long/path/page',
                value: 10,
                average_conversion_time: 5000,
            },
        ]
        const { nodes } = buildPathFlowElements(longUrlLinks, 'step-0', 'step-1')

        for (const node of nodes) {
            expect(node.data.displayName.length).toBeLessThanOrEqual(28)
        }
    })

    it('handles custom event names without URLs', () => {
        const customEventLinks: PathsLink[] = [
            { source: '1_$pageview', target: '2_button_clicked', value: 25, average_conversion_time: 1000 },
        ]
        const { nodes } = buildPathFlowElements(customEventLinks, 'step-0', 'step-1')

        expect(nodes[0].data.eventName).toBe('$pageview')
        expect(nodes[1].data.eventName).toBe('button_clicked')
    })

    it('skips source bridge edges when sourceStepId is null', () => {
        const { edges } = buildPathFlowElements(SAMPLE_LINKS, null, 'step-1')

        const bridgesFrom = edges.filter((e) => e.id.startsWith('bridge-from-'))
        expect(bridgesFrom).toHaveLength(0)

        const bridgesTo = edges.filter((e) => e.id.startsWith('bridge-to-'))
        expect(bridgesTo).toHaveLength(1)
    })

    it('skips target bridge edges when targetStepId is null', () => {
        const { edges } = buildPathFlowElements(SAMPLE_LINKS, 'step-0', null)

        const bridgesTo = edges.filter((e) => e.id.startsWith('bridge-to-'))
        expect(bridgesTo).toHaveLength(0)

        const bridgesFrom = edges.filter((e) => e.id.startsWith('bridge-from-'))
        expect(bridgesFrom).toHaveLength(1)
    })

    it('propagates isDropOff to source bridge edge data', () => {
        const { edges } = buildPathFlowElements(SAMPLE_LINKS, 'step-1', null, true)

        const bridgesFrom = edges.filter((e) => e.id.startsWith('bridge-from-'))
        expect(bridgesFrom).toHaveLength(1)
        expect(bridgesFrom[0].data?.isDropOff).toBe(true)
    })

    it('does not set isDropOff on source bridge edges by default', () => {
        const { edges } = buildPathFlowElements(SAMPLE_LINKS, 'step-0', 'step-1')

        const bridgesFrom = edges.filter((e) => e.id.startsWith('bridge-from-'))
        expect(bridgesFrom[0].data?.isDropOff).toBeUndefined()
    })
})

describe('bridgeConfigForExpansion', () => {
    it.each([
        {
            name: 'between at step 1',
            expansion: { stepIndex: 1, pathType: FunnelPathType.between, dropOff: false },
            expected: { sourceStepId: 'step-0', targetStepId: 'step-1', isDropOff: false, hiddenEdgeId: 'edge-0' },
        },
        {
            name: 'between at step 2',
            expansion: { stepIndex: 2, pathType: FunnelPathType.between, dropOff: false },
            expected: { sourceStepId: 'step-1', targetStepId: 'step-2', isDropOff: false, hiddenEdgeId: 'edge-1' },
        },
        {
            name: 'before step 1',
            expansion: { stepIndex: 1, pathType: FunnelPathType.before, dropOff: false },
            expected: { sourceStepId: null, targetStepId: 'step-1', isDropOff: false, hiddenEdgeId: null },
        },
        {
            name: 'before step 2',
            expansion: { stepIndex: 2, pathType: FunnelPathType.before, dropOff: false },
            expected: { sourceStepId: null, targetStepId: 'step-2', isDropOff: false, hiddenEdgeId: null },
        },
        {
            name: 'after step 0 (first step)',
            expansion: { stepIndex: 0, pathType: FunnelPathType.after, dropOff: false },
            expected: { sourceStepId: 'step-0', targetStepId: null, isDropOff: false, hiddenEdgeId: null },
        },
        {
            name: 'after step 2 (last step)',
            expansion: { stepIndex: 2, pathType: FunnelPathType.after, dropOff: false },
            expected: { sourceStepId: 'step-2', targetStepId: null, isDropOff: false, hiddenEdgeId: null },
        },
        {
            name: 'after dropoff at step 1',
            expansion: { stepIndex: 1, pathType: FunnelPathType.after, dropOff: true },
            expected: { sourceStepId: 'step-1', targetStepId: null, isDropOff: true, hiddenEdgeId: null },
        },
        {
            name: 'before dropoff at step 1',
            expansion: { stepIndex: 1, pathType: FunnelPathType.before, dropOff: true },
            expected: { sourceStepId: null, targetStepId: 'step-1', isDropOff: true, hiddenEdgeId: null },
        },
    ])('$name', ({ expansion, expected }) => {
        expect(bridgeConfigForExpansion(expansion)).toEqual(expected)
    })
})

describe('pathExpansionCacheKey', () => {
    it('produces unique keys for different expansions', () => {
        const expansions: PathExpansion[] = [
            { stepIndex: 1, pathType: FunnelPathType.before, dropOff: false },
            { stepIndex: 1, pathType: FunnelPathType.between, dropOff: false },
            { stepIndex: 1, pathType: FunnelPathType.after, dropOff: false },
            { stepIndex: 1, pathType: FunnelPathType.after, dropOff: true },
            { stepIndex: 1, pathType: FunnelPathType.before, dropOff: true },
            { stepIndex: 2, pathType: FunnelPathType.before, dropOff: false },
        ]
        const keys = expansions.map(pathExpansionCacheKey)
        expect(new Set(keys).size).toBe(keys.length)
    })
})

describe('buildPathFlowElements with funnel step dedup', () => {
    const DEDUP_LINKS: PathsLink[] = [
        { source: '1_Signed up', target: '2_/files', value: 40, average_conversion_time: 10000 },
        { source: '2_/files', target: '3_Interacted with file', value: 25, average_conversion_time: 20000 },
    ]

    const funnelSteps = new Map([
        ['Signed up', 'step-0'],
        ['Interacted with file', 'step-1'],
    ])

    it.each([
        {
            name: 'after step: first-layer node matching source step is removed',
            links: [
                { source: '1_Signed up', target: '2_/pricing', value: 50, average_conversion_time: 10000 },
                { source: '2_/pricing', target: '3_/checkout', value: 20, average_conversion_time: 5000 },
            ] as PathsLink[],
            sourceStepId: 'step-0',
            targetStepId: null,
            stepMap: funnelSteps,
            expectedNodeIds: ['path-2_/pricing', 'path-3_/checkout'],
            expectedBridgeFromCount: 0,
            expectedBridgeToCount: 0,
            expectedEdgePairs: [
                ['step-0', 'path-2_/pricing'],
                ['path-2_/pricing', 'path-3_/checkout'],
            ],
        },
        {
            name: 'between: boundary nodes matching source and target are both removed',
            links: DEDUP_LINKS,
            sourceStepId: 'step-0',
            targetStepId: 'step-1',
            stepMap: funnelSteps,
            expectedNodeIds: ['path-2_/files'],
            expectedBridgeFromCount: 0,
            expectedBridgeToCount: 0,
            expectedEdgePairs: [
                ['step-0', 'path-2_/files'],
                ['path-2_/files', 'step-1'],
            ],
        },
        {
            name: 'before step: intermediate node matching a funnel step is routed through it',
            links: [
                { source: '1_/home', target: '2_Signed up', value: 30, average_conversion_time: 10000 },
                { source: '2_Signed up', target: '3_/files', value: 20, average_conversion_time: 5000 },
                { source: '3_/files', target: '4_Interacted with file', value: 15, average_conversion_time: 3000 },
            ] as PathsLink[],
            sourceStepId: null,
            targetStepId: 'step-1',
            stepMap: funnelSteps,
            expectedNodeIds: ['path-1_/home', 'path-3_/files'],
            expectedBridgeFromCount: 0,
            expectedBridgeToCount: 0,
            expectedEdgePairs: [
                ['path-1_/home', 'step-0'],
                ['step-0', 'path-3_/files'],
                ['path-3_/files', 'step-1'],
            ],
        },
        {
            name: 'no dedup when map is undefined',
            links: DEDUP_LINKS,
            sourceStepId: 'step-0',
            targetStepId: 'step-1',
            stepMap: undefined,
            expectedNodeIds: ['path-1_Signed up', 'path-2_/files', 'path-3_Interacted with file'],
            expectedBridgeFromCount: 1,
            expectedBridgeToCount: 1,
            expectedEdgePairs: [
                ['step-0', 'path-1_Signed up'],
                ['path-1_Signed up', 'path-2_/files'],
                ['path-2_/files', 'path-3_Interacted with file'],
                ['path-3_Interacted with file', 'step-1'],
            ],
        },
        {
            name: 'no dedup when map is empty',
            links: DEDUP_LINKS,
            sourceStepId: 'step-0',
            targetStepId: 'step-1',
            stepMap: new Map<string, string>(),
            expectedNodeIds: ['path-1_Signed up', 'path-2_/files', 'path-3_Interacted with file'],
            expectedBridgeFromCount: 1,
            expectedBridgeToCount: 1,
            expectedEdgePairs: [
                ['step-0', 'path-1_Signed up'],
                ['path-1_Signed up', 'path-2_/files'],
                ['path-2_/files', 'path-3_Interacted with file'],
                ['path-3_Interacted with file', 'step-1'],
            ],
        },
        {
            name: 'bridge kept when first-layer node maps to a different funnel step',
            links: [
                { source: '1_Interacted with file', target: '2_/other', value: 10, average_conversion_time: 5000 },
            ] as PathsLink[],
            sourceStepId: 'step-0',
            targetStepId: null,
            stepMap: funnelSteps,
            expectedNodeIds: ['path-2_/other'],
            expectedBridgeFromCount: 1,
            expectedBridgeToCount: 0,
            expectedEdgePairs: [
                ['step-0', 'step-1'],
                ['step-1', 'path-2_/other'],
            ],
        },
    ])(
        '$name',
        ({
            links,
            sourceStepId,
            targetStepId,
            stepMap,
            expectedNodeIds,
            expectedBridgeFromCount,
            expectedBridgeToCount,
            expectedEdgePairs,
        }) => {
            const { nodes, edges } = buildPathFlowElements(links, sourceStepId, targetStepId, undefined, stepMap)

            expect(nodes.map((n) => n.id).sort()).toEqual(expectedNodeIds.sort())

            const bridgesFrom = edges.filter((e) => e.id.startsWith('bridge-from-'))
            expect(bridgesFrom).toHaveLength(expectedBridgeFromCount)

            const bridgesTo = edges.filter((e) => e.id.startsWith('bridge-to-'))
            expect(bridgesTo).toHaveLength(expectedBridgeToCount)

            const edgePairs = edges.map((e) => [e.source, e.target])
            expect(edgePairs).toEqual(expectedEdgePairs)
        }
    )

    it('drops self-loop edges when source and target resolve to the same funnel step', () => {
        const selfLoopLinks: PathsLink[] = [
            { source: '1_Signed up', target: '2_Signed up', value: 10, average_conversion_time: 1000 },
            { source: '2_Signed up', target: '3_/other', value: 5, average_conversion_time: 2000 },
        ]
        const { nodes, edges } = buildPathFlowElements(selfLoopLinks, 'step-0', null, undefined, funnelSteps)

        expect(nodes.map((n) => n.id)).toEqual(['path-3_/other'])

        const selfLoops = edges.filter((e) => e.source === e.target)
        expect(selfLoops).toHaveLength(0)

        expect(edges.map((e) => [e.source, e.target])).toEqual([['step-0', 'path-3_/other']])
    })

    it('rewrites handle IDs to match the replacement funnel step node', () => {
        const links: PathsLink[] = [
            { source: '1_Signed up', target: '2_/other', value: 10, average_conversion_time: 5000 },
        ]
        const { edges } = buildPathFlowElements(links, 'step-0', null, undefined, funnelSteps)

        const pathEdge = edges.find((e) => e.id.startsWith('path-edge-'))!
        expect(pathEdge.sourceHandle).toBe('step-0-source')
        expect(pathEdge.targetHandle).toBe('path-2_/other-target')
    })
})

describe('buildPathsQuery', () => {
    const querySource = {
        kind: NodeKind.FunnelsQuery,
        series: [],
        dateRange: { date_from: '-7d' },
    } as FunnelsQuery

    it.each([
        {
            name: 'between at step 1 (funnelStep = 2)',
            expansion: { stepIndex: 1, pathType: FunnelPathType.between, dropOff: false },
            expectedStep: 2,
            expectedPathType: FunnelPathType.between,
        },
        {
            name: 'before step 2 (funnelStep = 3)',
            expansion: { stepIndex: 2, pathType: FunnelPathType.before, dropOff: false },
            expectedStep: 3,
            expectedPathType: FunnelPathType.before,
        },
        {
            name: 'after step 0 (funnelStep = 1)',
            expansion: { stepIndex: 0, pathType: FunnelPathType.after, dropOff: false },
            expectedStep: 1,
            expectedPathType: FunnelPathType.after,
        },
        {
            name: 'after dropoff at step 1 (funnelStep = -2)',
            expansion: { stepIndex: 1, pathType: FunnelPathType.after, dropOff: true },
            expectedStep: -2,
            expectedPathType: FunnelPathType.after,
        },
        {
            name: 'before dropoff at step 2 (funnelStep = -3)',
            expansion: { stepIndex: 2, pathType: FunnelPathType.before, dropOff: true },
            expectedStep: -3,
            expectedPathType: FunnelPathType.before,
        },
    ])('$name', ({ expansion, expectedStep, expectedPathType }) => {
        const query = buildPathsQuery(expansion, querySource)

        expect(query.funnelPathsFilter?.funnelStep).toBe(expectedStep)
        expect(query.funnelPathsFilter?.funnelPathType).toBe(expectedPathType)
        expect(query.dateRange?.date_from).toBe('-7d')
    })
})
