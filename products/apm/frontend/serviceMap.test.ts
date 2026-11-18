import { buildServiceGraph } from './serviceMap'

const service = (service_name: string, status: 'good' | 'serious'): any => ({
    service_name,
    environment: 'prod',
    status,
    health: { request_rate: 1, error_rate: status === 'good' ? 0 : 0.1, p95_ms: 10, span_count: 10, error_count: 0 },
    sparkline: [],
})

const edge = (caller: string, callee: string, calls: number, error_count = 0): any => ({
    caller,
    callee,
    calls,
    error_count,
    p95_ms: 5,
})

describe('buildServiceGraph', () => {
    it('makes one node per service seen in the health rows or the edges, with health when known', () => {
        const graph = buildServiceGraph(
            [service('web', 'good'), service('api', 'serious'), service('lonely', 'good')],
            [edge('web', 'api', 10), edge('api', 'db', 4)]
        )
        expect(graph.nodes.map((n) => n.id).sort()).toEqual(['api', 'db', 'lonely', 'web'])
        const byId = Object.fromEntries(graph.nodes.map((n) => [n.id, n.data]))
        expect(byId.api.service?.status).toBe('serious')
        // A callee with no health row in this environment still gets a node, with no health.
        expect(byId.db.service).toBeNull()
    })

    it('scales edge width by calls and carries the error rate', () => {
        const graph = buildServiceGraph([], [edge('web', 'api', 10, 5), edge('api', 'db', 1)])
        const byId = Object.fromEntries(graph.edges.map((e) => [e.id, e]))
        expect(byId['web->api'].source).toBe('web')
        expect(byId['web->api'].target).toBe('api')
        expect(byId['web->api'].data?.errorRate).toBe(0.5)
        expect(byId['web->api'].data!.width).toBeGreaterThan(byId['api->db'].data!.width)
        expect(byId['api->db'].data!.width).toBeGreaterThanOrEqual(1)
    })

    it('returns an empty graph when there is nothing to draw', () => {
        expect(buildServiceGraph([], [])).toEqual({ nodes: [], edges: [] })
    })
})
