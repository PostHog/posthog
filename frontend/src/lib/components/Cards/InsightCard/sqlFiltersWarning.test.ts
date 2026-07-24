import { Node, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { dashboardFiltersIgnoredOnSqlInsight } from './sqlFiltersWarning'

const hostFilter: AnyPropertyFilter = {
    type: PropertyFilterType.Event,
    key: '$host',
    operator: PropertyOperator.Exact,
    value: ['example.com'],
}

const hogQLQuery = (query: string): Node => ({ kind: NodeKind.HogQLQuery, query }) as Node

const dataVizNode = (query: string): Node =>
    ({ kind: NodeKind.DataVisualizationNode, source: { kind: NodeKind.HogQLQuery, query } }) as Node

const trendsInsightVizNode: Node = {
    kind: NodeKind.InsightVizNode,
    source: { kind: NodeKind.TrendsQuery, series: [] },
} as Node

describe('dashboardFiltersIgnoredOnSqlInsight', () => {
    it.each<[string, Node | null, AnyPropertyFilter[] | null, boolean]>([
        // The reported bug: SQL insight with no {filters} + dashboard property filter → warn
        ['bare HogQLQuery without {filters}', hogQLQuery('SELECT event FROM events'), [hostFilter], true],
        ['DataVisualizationNode without {filters}', dataVizNode('SELECT event FROM events'), [hostFilter], true],
        // Placeholder present → filter is applied, no warning
        ['HogQLQuery with {filters}', hogQLQuery('SELECT event FROM events WHERE {filters}'), [hostFilter], false],
        [
            'DataVisualizationNode with {filters}',
            dataVizNode('SELECT event FROM events WHERE {filters}'),
            [hostFilter],
            false,
        ],
        // {filters} only inside a string literal or comment doesn't count as a real placeholder
        [
            'placeholder only in a comment',
            hogQLQuery('SELECT event FROM events -- WHERE {filters}'),
            [hostFilter],
            true,
        ],
        // No property filters → nothing to drop, no warning
        ['no property filters', hogQLQuery('SELECT event FROM events'), [], false],
        ['null property filters', hogQLQuery('SELECT event FROM events'), null, false],
        // Non-SQL insights merge into a real query.properties, so they aren't affected
        ['trends insight', trendsInsightVizNode, [hostFilter], false],
        ['null query', null, [hostFilter], false],
    ])('%s', (_name, query, propertyFilters, expected) => {
        expect(dashboardFiltersIgnoredOnSqlInsight(query, propertyFilters)).toBe(expected)
    })
})
