import {
    buildDependencyGraph,
    edgesToDraw,
    graphKey,
    groupExternalHosts,
    serviceNamesOf,
    splitDependencies,
} from './dependencies'
import type { DependencyEdgeApi } from './generated/api.schemas'

const edge = (caller: string, callee: string, overrides: Partial<DependencyEdgeApi> = {}): DependencyEdgeApi => ({
    caller,
    callee,
    inferred: false,
    kind: 'service',
    requests: 10,
    error_count: 0,
    p95_ms: 5,
    ...overrides,
})

describe('dependencies', () => {
    const edges = [
        edge('web', 'api'),
        edge('api', 'postgresql:orders', { inferred: true, kind: 'database', requests: 20, error_count: 5 }),
        edge('api', 'payments', { inferred: true, kind: 'service' }),
        edge('payments', 'bank'),
    ]

    it('splits one service into callers and callees', () => {
        const { upstream, downstream } = splitDependencies(edges, 'api')
        expect(upstream.map((e) => e.caller)).toEqual(['web'])
        expect(downstream.map((e) => e.callee)).toEqual(['postgresql:orders', 'payments'])
    })

    it('lists only names that send spans as services', () => {
        expect(serviceNamesOf(edges)).toEqual(['api', 'bank', 'payments', 'web'])
    })

    it('draws an inferred callee dashed unless it also calls out', () => {
        const nodes = Object.fromEntries(buildDependencyGraph(edges).nodes.map((node) => [node.id, node.data]))
        expect(nodes['postgresql:orders']).toMatchObject({ inferred: true, kind: 'database', errorRate: 0.25 })
        expect(nodes['payments']).toMatchObject({ inferred: false, kind: 'service' })
    })

    const many = Array.from({ length: 50 }, (_, i) => edge('gateway', `svc-${i}`, { requests: i + 1 }))

    it.each([
        { name: 'caps all services to the 40 busiest', service: null, showAll: false, count: 40, minRequests: 11 },
        {
            name: 'draws every call for a picked service',
            service: 'gateway',
            showAll: false,
            count: 50,
            minRequests: 1,
        },
        { name: 'draws every call after Show all', service: null, showAll: true, count: 50, minRequests: 1 },
    ])('$name', ({ service, showAll, count, minRequests }) => {
        const drawn = edgesToDraw(many, service, showAll)
        expect(drawn).toHaveLength(count)
        expect(Math.min(...drawn.map((e) => e.requests))).toBe(minRequests)
    })

    const hosts = (caller: string, count: number): DependencyEdgeApi[] =>
        Array.from({ length: count }, (_, i) =>
            edge(caller, `api${i}.example.com`, {
                inferred: true,
                kind: 'external',
                requests: 10,
                error_count: 1,
                p95_ms: 100 + i,
            })
        )

    it('merges a caller with more than 5 external hosts into one node', () => {
        const grouped = groupExternalHosts([edge('web', 'api'), ...hosts('checkout', 6), ...hosts('search', 5)])
        expect(grouped.filter((e) => e.caller === 'search')).toHaveLength(5)
        expect(grouped.filter((e) => e.caller === 'checkout')).toEqual([
            expect.objectContaining({
                requests: 60,
                error_count: 6,
                p95_ms: 105,
                group: { caller: 'checkout', hostCount: 6, p95MaxMs: 105 },
            }),
        ])
    })

    it('lists each external host once a service is picked', () => {
        expect(edgesToDraw(hosts('checkout', 8), 'checkout', false)).toHaveLength(8)
    })

    it('refits the map only when the drawn nodes or edges change', () => {
        const busiest = buildDependencyGraph(edgesToDraw(many, null, false))
        const busier = buildDependencyGraph(
            edgesToDraw(
                many.map((e) => ({ ...e, requests: e.requests * 2 })),
                null,
                false
            )
        )
        expect(graphKey(busier)).toBe(graphKey(busiest))
        const all = graphKey(buildDependencyGraph(edgesToDraw(many, null, true)))
        expect(graphKey(buildDependencyGraph(edgesToDraw([...many].reverse(), null, true)))).toBe(all)
        expect(all).not.toBe(graphKey(busiest))
    })
})
