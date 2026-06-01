import { lookupMcpToolRenderer, mcpToolRegistry } from './mcpToolRegistry'
import { CreateInsightAdapter } from './messages/adapters/CreateInsightAdapter'
import { ErrorTrackingAdapter } from './messages/adapters/ErrorTrackingAdapter'
import { SearchSessionRecordingsAdapter } from './messages/adapters/SearchSessionRecordingsAdapter'
import { UpsertDashboardAdapter } from './messages/adapters/UpsertDashboardAdapter'
import { FallbackMcpToolRenderer } from './messages/FallbackMcpToolRenderer'

describe('mcpToolRegistry data-tool adapters', () => {
    const cases: [string, React.ComponentType<any>][] = [
        ['insight-create', CreateInsightAdapter],
        ['insight-update', CreateInsightAdapter],
        ['insight-query', CreateInsightAdapter],
        ['create_insight', CreateInsightAdapter],
        ['edit_insight', CreateInsightAdapter],
        ['read_insight', CreateInsightAdapter],
        ['dashboard-create', UpsertDashboardAdapter],
        ['upsert_dashboard', UpsertDashboardAdapter],
        ['query-session-recordings-list', SearchSessionRecordingsAdapter],
        ['search_session_recordings', SearchSessionRecordingsAdapter],
        ['filter_session_recordings', SearchSessionRecordingsAdapter],
        ['query-error-tracking-issues-list', ErrorTrackingAdapter],
        ['search_error_tracking_issues', ErrorTrackingAdapter],
        ['filter_error_tracking_issues', ErrorTrackingAdapter],
    ]

    it.each(cases)('resolves %s to its data-tool adapter', (key, expectedRenderer) => {
        const entry = mcpToolRegistry.lookup(key)
        expect(entry).not.toBeNull()
        expect(entry?.Renderer).toBe(expectedRenderer)
        // lookupMcpToolRenderer returns the same registered entry, not the fallback.
        expect(lookupMcpToolRenderer(key).Renderer).toBe(expectedRenderer)
    })

    it('falls back to FallbackMcpToolRenderer for unknown / unregistered tool names', () => {
        expect(mcpToolRegistry.lookup('mcp__user-installed__something')).toBeNull()
        expect(lookupMcpToolRenderer('mcp__user-installed__something').Renderer).toBe(FallbackMcpToolRenderer)
        // An inner tool we have not wired an adapter for also falls through.
        expect(lookupMcpToolRenderer('experiment-create').Renderer).toBe(FallbackMcpToolRenderer)
    })
})
