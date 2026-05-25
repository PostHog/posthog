import { DataVisualizationNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType, FilterLogicalOperator } from '~/types'

import { buildRecordingFiltersFromQuery, deriveInsightName } from './visualizationArtifactAnswer.helpers'

const trendsWithEvents = (events: (string | null)[]): InsightVizNode => ({
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.TrendsQuery,
        series: events.map((event) =>
            event
                ? { kind: NodeKind.EventsNode, event, math: BaseMathType.TotalCount }
                : { kind: NodeKind.ActionsNode, id: 1 }
        ),
    } as InsightVizNode['source'],
})

const hogQLDataVisualization = (): DataVisualizationNode =>
    ({
        kind: NodeKind.DataVisualizationNode,
        source: { kind: NodeKind.HogQLQuery, query: 'select 1' },
    }) as DataVisualizationNode

describe('VisualizationArtifactAnswer helpers', () => {
    describe('buildRecordingFiltersFromQuery', () => {
        it.each([
            ['no series at all (hogql)', hogQLDataVisualization()],
            ['series with only an action node', trendsWithEvents([null])],
        ])('returns null for %s', (_label, query) => {
            const result = buildRecordingFiltersFromQuery(query as InsightVizNode | DataVisualizationNode)
            expect(result).toBeNull()
        })

        it.each([
            ['series with one event', trendsWithEvents(['$pageview']), ['$pageview']],
            ['series with two events', trendsWithEvents(['$pageview', 'sign up']), ['$pageview', 'sign up']],
            [
                'mixed events and actions — actions are skipped',
                trendsWithEvents(['$pageview', null, 'sign up']),
                ['$pageview', 'sign up'],
            ],
        ])('returns event filters for %s', (_label, query, expected) => {
            const result = buildRecordingFiltersFromQuery(query as InsightVizNode | DataVisualizationNode)
            expect(result).not.toBeNull()
            expect(result!.filter_group!.type).toBe(FilterLogicalOperator.And)
            const inner = result!.filter_group!.values[0] as { type: FilterLogicalOperator; values: { id: string }[] }
            expect(inner.type).toBe(FilterLogicalOperator.And)
            const ids = inner.values.map((value) => value.id)
            expect(ids).toEqual(expected)
        })
    })

    describe('deriveInsightName', () => {
        it.each([
            ['series with a named event', trendsWithEvents(['$pageview']), 'Max - $pageview'],
            [
                'series with multiple events uses the first one',
                trendsWithEvents(['$pageview', 'sign up']),
                'Max - $pageview',
            ],
            ['series with only action nodes falls back', trendsWithEvents([null]), 'Max-generated insight'],
            ['hogql data visualization falls back', hogQLDataVisualization(), 'Max-generated insight'],
        ])('names %s correctly', (_label, query, expected) => {
            expect(deriveInsightName(query as InsightVizNode | DataVisualizationNode)).toBe(expected)
        })
    })
})
