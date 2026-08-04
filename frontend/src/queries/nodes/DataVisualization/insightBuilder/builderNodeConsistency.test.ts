import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { builderConfigMatchesQuery, compileNodeBuilder, nodeOpensInBuilder } from './builderNodeConsistency'

const BASE_QUERY = 'select event, uniq(distinct_id) as users from events group by event'

// A config the current compiler round-trips (mirrors a saved builder insight)
function selfConsistentNode(): DataVisualizationNode {
    const builder = {
        enabled: true,
        baseQuery: BASE_QUERY,
        rows: [],
        columns: [{ column: 'event' }],
        values: [{ column: 'users', aggregation: 'sum' as const }],
    }
    return {
        kind: NodeKind.DataVisualizationNode,
        source: {
            kind: NodeKind.HogQLQuery,
            query: compileNodeBuilder(builder, ChartDisplayType.ActionsLineGraph).sql,
        },
        display: ChartDisplayType.ActionsLineGraph,
        builder,
    }
}

describe('builderConfigMatchesQuery', () => {
    it('trusts the compiledQuery snapshot over recompilation', () => {
        // The saved SQL matches the snapshot but NOT what today's compiler would emit — the
        // insight was saved by an older compiler. It must still hydrate: drift in compiler
        // output must not orphan previously saved builder insights.
        const oldCompilerSql = 'SELECT event, sum(users) AS legacy_alias FROM (events_base) GROUP BY event'
        const node = selfConsistentNode()
        node.source.query = oldCompilerSql
        node.builder!.compiledQuery = oldCompilerSql

        expect(builderConfigMatchesQuery(node)).toBe(true)
    })

    it('flags externally edited SQL against the snapshot', () => {
        const node = selfConsistentNode()
        node.builder!.compiledQuery = node.source.query
        node.source.query = 'SELECT edited_elsewhere FROM events'

        expect(builderConfigMatchesQuery(node)).toBe(false)
    })

    it('falls back to recompiling for configs saved before compiledQuery existed', () => {
        const consistent = selfConsistentNode()
        expect(consistent.builder!.compiledQuery).toBeUndefined()
        expect(builderConfigMatchesQuery(consistent)).toBe(true)

        const edited = selfConsistentNode()
        edited.source.query = 'SELECT edited_elsewhere FROM events'
        expect(builderConfigMatchesQuery(edited)).toBe(false)
    })

    it('ignores whitespace-only differences from the snapshot', () => {
        const node = selfConsistentNode()
        node.builder!.compiledQuery = node.source.query
        node.source.query = `${node.source.query.replace(/\s+/g, '  ')}\n`

        expect(builderConfigMatchesQuery(node)).toBe(true)
    })
})

describe('nodeOpensInBuilder', () => {
    it('is false for a missing node', () => {
        expect(nodeOpensInBuilder(undefined)).toBe(false)
        expect(nodeOpensInBuilder(null)).toBe(false)
    })

    it('is false for a classic node without a builder config', () => {
        const node = selfConsistentNode()
        delete node.builder
        expect(nodeOpensInBuilder(node)).toBe(false)
    })

    it('is false for a disabled builder config', () => {
        const node = selfConsistentNode()
        node.builder!.enabled = false
        expect(nodeOpensInBuilder(node)).toBe(false)
    })

    it('is true for a consistent builder node and false once its SQL is edited elsewhere', () => {
        const consistent = selfConsistentNode()
        expect(nodeOpensInBuilder(consistent)).toBe(true)

        const stale = selfConsistentNode()
        stale.builder!.compiledQuery = stale.source.query
        stale.source.query = 'SELECT edited_elsewhere FROM events'
        expect(nodeOpensInBuilder(stale)).toBe(false)
    })
})
