import { lookupMcpToolRenderer, mcpToolRegistry } from './mcpToolRegistry'
import { CreateInsightWidget } from './messages/adapters/CreateInsightWidget'
import { ErrorTrackingWidget } from './messages/adapters/ErrorTrackingWidget'
import { QueryWidget } from './messages/adapters/QueryWidget'
import { SearchSessionRecordingsWidget } from './messages/adapters/SearchSessionRecordingsWidget'
import { UpsertDashboardWidget } from './messages/adapters/UpsertDashboardWidget'
import { FallbackMcpToolRenderer } from './messages/FallbackMcpToolRenderer'

describe('mcpToolRegistry data-tool widgets', () => {
    const cases: [string, React.ComponentType<any>][] = [
        ['insight-create', CreateInsightWidget],
        ['insight-update', CreateInsightWidget],
        ['insight-get', CreateInsightWidget],
        ['create_insight', CreateInsightWidget],
        ['dashboard-create', UpsertDashboardWidget],
        ['dashboard-update', UpsertDashboardWidget],
        ['upsert_dashboard', UpsertDashboardWidget],
        ['query-session-recordings-list', SearchSessionRecordingsWidget],
        ['search_session_recordings', SearchSessionRecordingsWidget],
        ['filter_session_recordings', SearchSessionRecordingsWidget],
        ['query-error-tracking-issues-list', ErrorTrackingWidget],
        ['search_error_tracking_issues', ErrorTrackingWidget],
        ['filter_error_tracking_issues', ErrorTrackingWidget],
        ['query-trends', QueryWidget],
        ['query-funnel', QueryWidget],
        ['query-retention', QueryWidget],
        ['query-stickiness', QueryWidget],
        ['query-paths', QueryWidget],
        ['query-lifecycle', QueryWidget],
        ['query-llm-traces-list', QueryWidget],
        ['query-trends-actors', QueryWidget],
        ['query-lifecycle-actors', QueryWidget],
        ['query-paths-actors', QueryWidget],
    ]

    it.each(cases)('resolves %s to its data-tool widget', (key, expectedRenderer) => {
        const entry = mcpToolRegistry.lookup(key)
        expect(entry).not.toBeNull()
        expect(entry?.Renderer).toBe(expectedRenderer)
        // lookupMcpToolRenderer returns the same registered entry, not the fallback.
        expect(lookupMcpToolRenderer(key).Renderer).toBe(expectedRenderer)
    })

    it('falls back to FallbackMcpToolRenderer for unknown / unregistered tool names', () => {
        expect(mcpToolRegistry.lookup('mcp__user-installed__something')).toBeNull()
        expect(lookupMcpToolRenderer('mcp__user-installed__something').Renderer).toBe(FallbackMcpToolRenderer)
        // An inner tool we have not wired a widget for also falls through.
        expect(lookupMcpToolRenderer('experiment-create').Renderer).toBe(FallbackMcpToolRenderer)
        // Names that exist in no tool definition stay unregistered.
        expect(mcpToolRegistry.lookup('insight-query')).toBeNull()
        expect(mcpToolRegistry.lookup('read_insight')).toBeNull()
        // A single LLM trace has no inline renderer, so the tool stays on the fallback card.
        expect(mcpToolRegistry.lookup('query-llm-trace')).toBeNull()
    })
})
