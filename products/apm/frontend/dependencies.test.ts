import { buildDependencyGraph, serviceNamesOf, splitDependencies } from './dependencies'
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
})
