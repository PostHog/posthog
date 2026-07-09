import { ArtifactSource } from '~/queries/schema/schema-assistant-messages'

import type { ToolCallMessage } from '../../maxTypes'
import {
    extractDashboard,
    extractErrorTrackingResponse,
    extractQueryResult,
    extractRecordingFilters,
    extractVisualizationArtifact,
} from './extractors'

function toolMessage(
    rawOutput: unknown,
    innerInput?: Record<string, unknown>,
    resolvedKey = 'test-tool'
): ToolCallMessage {
    return {
        id: 'call-1',
        resolvedKey,
        rawServerName: 'posthog',
        rawToolName: 'mcp__posthog__exec',
        rawInput: {},
        innerInput,
        rawOutput,
        content: [],
        status: 'completed',
    }
}

describe('mcp tool adapter extractors', () => {
    describe('extractVisualizationArtifact', () => {
        it('classifies a REST insight payload with short_id as a saved insight', () => {
            const artifact = extractVisualizationArtifact(
                toolMessage({ short_id: 'abc12345', name: 'Signups', query: { kind: 'TrendsQuery' } })
            )
            expect(artifact?.envelope.source).toBe(ArtifactSource.Insight)
            expect(artifact?.envelope.artifact_id).toBe('abc12345')
            expect(artifact?.content.name).toBe('Signups')
        })

        it('classifies a query-only output as ephemeral', () => {
            const artifact = extractVisualizationArtifact(toolMessage({ query: { kind: 'TrendsQuery' }, results: [] }))
            expect(artifact?.envelope.source).toBe(ArtifactSource.State)
            expect(artifact?.envelope.artifact_id).toBe('call-1')
        })

        it('returns null when the output has no query', () => {
            expect(extractVisualizationArtifact(toolMessage({ id: 1, name: 'No query here' }))).toBeNull()
            expect(extractVisualizationArtifact(toolMessage(undefined))).toBeNull()
        })
    })

    describe('extractDashboard', () => {
        it('reads id and the _posthogUrl enrichment from the REST payload', () => {
            const dashboard = extractDashboard(
                toolMessage({ id: 42, name: 'KPIs', _posthogUrl: 'https://us.posthog.com/project/1/dashboard/42' })
            )
            expect(dashboard).toEqual({
                id: 42,
                name: 'KPIs',
                url: 'https://us.posthog.com/project/1/dashboard/42',
            })
        })

        it('falls back to legacy dashboard_id / url fields and the input name', () => {
            const dashboard = extractDashboard(
                toolMessage({ dashboard_id: '7', url: '/dashboard/7' }, { name: 'From input' })
            )
            expect(dashboard).toEqual({ id: '7', name: 'From input', url: '/dashboard/7' })
        })
    })

    describe('extractRecordingFilters', () => {
        it('maps the query-wrapper output back to universal filters', () => {
            const filters = extractRecordingFilters(
                toolMessage({
                    query: {
                        kind: 'RecordingsQuery',
                        date_from: '-7d',
                        filter_test_accounts: true,
                        properties: [{ type: 'person', key: 'email', operator: 'icontains', value: 'posthog' }],
                    },
                    results: [],
                    _posthogUrl: 'https://us.posthog.com/project/1/replay',
                })
            )
            expect(filters?.date_from).toBe('-7d')
            expect(filters?.filter_test_accounts).toBe(true)
            expect(filters?.filter_group.values).toEqual([
                {
                    type: 'AND',
                    values: [{ type: 'person', key: 'email', operator: 'icontains', value: 'posthog' }],
                },
            ])
        })

        it('passes through a ready-made universal filters object', () => {
            const universal = {
                date_from: '-3d',
                duration: [],
                filter_group: { type: 'AND', values: [] },
            }
            expect(extractRecordingFilters(toolMessage({ filters: universal }))).toBe(universal)
        })

        it('returns null for outputs carrying neither shape', () => {
            expect(extractRecordingFilters(toolMessage({ results: [] }))).toBeNull()
            expect(extractRecordingFilters(toolMessage({ filters: { some: 'garbage' } }))).toBeNull()
            expect(extractRecordingFilters(toolMessage(undefined))).toBeNull()
        })
    })

    describe('extractErrorTrackingResponse', () => {
        it('accepts outputs carrying known search-response fields', () => {
            const response = { status: 'active', search_query: 'TypeError', issues: [] }
            expect(extractErrorTrackingResponse(toolMessage(response))).toBe(response)
        })

        it('rejects outputs without any known field', () => {
            expect(extractErrorTrackingResponse(toolMessage({ results: [{ id: 'issue-1' }] }))).toBeNull()
            expect(extractErrorTrackingResponse(toolMessage(undefined))).toBeNull()
        })
    })

    describe('extractQueryResult', () => {
        it.each(['TrendsQuery', 'FunnelsQuery', 'RetentionQuery', 'StickinessQuery', 'PathsQuery', 'LifecycleQuery'])(
            'passes a bare %s through for InsightVizNode wrapping downstream',
            (kind) => {
                const result = extractQueryResult(
                    toolMessage({
                        query: { kind, series: [] },
                        results: [],
                        _posthogUrl: 'https://us.posthog.com/insights/new',
                    })
                )
                expect(result?.content.query).toEqual({ kind, series: [] })
                expect(result?.url).toBe('https://us.posthog.com/insights/new')
            }
        )

        it('wraps a TracesQuery in a DataTableNode', () => {
            const result = extractQueryResult(toolMessage({ query: { kind: 'TracesQuery' }, results: [] }))
            expect(result?.content.query).toEqual({ kind: 'DataTableNode', source: { kind: 'TracesQuery' } })
            expect(result?.url).toBeNull()
        })

        it('uses the tool input when optimized streamed results omit structured raw output', () => {
            const result = extractQueryResult(
                toolMessage(undefined, { kind: 'TrendsQuery', series: [], output_format: 'optimized' }, 'query-trends')
            )
            expect(result?.content.query).toEqual({ kind: 'TrendsQuery', series: [] })
            expect(result?.url).toBeNull()
        })

        it('infers the query kind from the wrapper tool key when the input omits kind', () => {
            const result = extractQueryResult(toolMessage(undefined, { series: [] }, 'query-trends'))
            expect(result?.content.query).toEqual({ kind: 'TrendsQuery', series: [] })
        })

        it('wraps the actors wrapper output (ActorsQuery envelope) untouched in a DataTableNode', () => {
            const actorsQuery = {
                kind: 'ActorsQuery',
                source: { kind: 'InsightActorsQuery', source: { kind: 'TrendsQuery' } },
                select: ['actor'],
            }
            const result = extractQueryResult(
                toolMessage({ query: actorsQuery, results: { columns: [], results: [] } })
            )
            expect(result?.content.query).toEqual({ kind: 'DataTableNode', source: actorsQuery })
        })

        it('wraps a bare InsightActorsQuery in an ActorsQuery before the DataTableNode', () => {
            const insightActors = { kind: 'InsightActorsQuery', source: { kind: 'TrendsQuery' } }
            const result = extractQueryResult(toolMessage({ query: insightActors }))
            expect(result?.content.query).toEqual({
                kind: 'DataTableNode',
                source: { kind: 'ActorsQuery', source: insightActors, select: ['actor'] },
            })
        })

        it('returns null for kinds without an inline renderer or malformed outputs', () => {
            expect(extractQueryResult(toolMessage({ query: { kind: 'TraceQuery', traceId: 't1' } }))).toBeNull()
            expect(extractQueryResult(toolMessage({ results: [] }))).toBeNull()
            expect(extractQueryResult(toolMessage({ query: 'not-an-object' }))).toBeNull()
            expect(extractQueryResult(toolMessage(undefined))).toBeNull()
        })
    })
})
