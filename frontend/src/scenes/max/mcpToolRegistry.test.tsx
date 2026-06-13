import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import type { McpToolCallMessage } from './maxTypes'
import { lookupMcpToolRenderer, mcpToolRegistry } from './mcpToolRegistry'
import { CreateInsightWidget } from './messages/adapters/CreateInsightWidget'
import { ErrorTrackingWidget } from './messages/adapters/ErrorTrackingWidget'
import { QueryWidget } from './messages/adapters/QueryWidget'
import { SearchSessionRecordingsWidget } from './messages/adapters/SearchSessionRecordingsWidget'
import { UpsertDashboardWidget } from './messages/adapters/UpsertDashboardWidget'
import { FallbackMcpToolRenderer } from './messages/FallbackMcpToolRenderer'

function makeMessage(overrides: Partial<McpToolCallMessage> = {}): McpToolCallMessage {
    return {
        id: 'tc-1',
        resolvedKey: 'Edit',
        rawServerName: 'posthog',
        rawToolName: '',
        rawInput: {},
        content: [],
        status: 'completed',
        ...overrides,
    }
}

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

    // Claude built-ins are keyed by their stable SDK name and all reuse the fallback renderer; the
    // registry contributes a friendly displayName + icon (not the wrench fallback's resolvedKey/wrench).
    const builtinCases: [string, string][] = [
        ['Read', 'Read'],
        ['NotebookRead', 'Read'],
        ['Edit', 'Edit'],
        ['Write', 'Edit'],
        ['NotebookEdit', 'Edit'],
        ['MultiEdit', 'Edit'],
        ['Grep', 'Search'],
        ['Glob', 'Search'],
        ['LS', 'Search'],
        ['Bash', 'Terminal'],
        ['BashOutput', 'Terminal'],
        ['KillShell', 'Terminal'],
        ['WebSearch', 'Web'],
        ['WebFetch', 'Web'],
        ['Task', 'Subagent'],
        ['Agent', 'Subagent'],
        ['TaskCreate', 'Tasks'],
        ['TaskUpdate', 'Tasks'],
        ['TaskGet', 'Tasks'],
        ['TaskList', 'Tasks'],
        ['TodoWrite', 'Tasks'],
        ['Skill', 'Skill'],
        ['ToolSearch', 'Tool search'],
        ['ExitPlanMode', 'Plan'],
        ['AskUserQuestion', 'Question'],
    ]

    it.each(builtinCases)('resolves built-in %s to a registered entry with displayName "%s"', (key, displayName) => {
        // A registered built-in entry exists — the lookup is not the synthesized wrench fallback.
        const entry = mcpToolRegistry.lookup(key)
        expect(entry).not.toBeNull()
        expect(entry?.displayName).toEqual(displayName)
        expect(lookupMcpToolRenderer(key).displayName).toEqual(displayName)
    })

    it('still falls back to the wrench card for an unmapped built-in-looking name', () => {
        expect(mcpToolRegistry.lookup('NotARealTool')).toBeNull()
        const fallback = lookupMcpToolRenderer('NotARealTool')
        expect(fallback.displayName).toEqual('NotARealTool')
        expect(fallback.Renderer).toBe(FallbackMcpToolRenderer)
    })

    // Render-level: the registry's icon/displayName must actually reach the card, not just the entry.
    // This is the regression the entry-only assertions above cannot catch — the card hard-coded a
    // wrench and ignored the entry, so a built-in still rendered identically to the fallback.
    describe('rendered card consumes the registry entry', () => {
        it('renders the registry icon (not the wrench) and the displayName as the header', () => {
            const entry = lookupMcpToolRenderer('Edit')
            const message = makeMessage({ resolvedKey: 'Edit', title: '' })
            // Mounted exactly as Thread.tsx mounts it: pass the resolved entry's icon + displayName.
            render(
                <entry.Renderer
                    message={message}
                    isLastInGroup
                    icon={<span data-attr="resolved-icon">icon</span>}
                    displayName={entry.displayName}
                />
            )
            // The friendly displayName is the header label when the wire title is empty.
            expect(screen.getByText('Edit')).toBeInTheDocument()
            // The provided icon renders — the card no longer ignores props.icon in favor of the wrench.
            expect(screen.getByTestId('resolved-icon')).toBeInTheDocument()
        })

        it('prefers the wire title over the displayName when a title is present', () => {
            const message = makeMessage({ resolvedKey: 'Edit', title: 'Edit `foo.ts`' })
            render(<FallbackMcpToolRenderer message={message} displayName="Edit" isLastInGroup />)
            expect(screen.getByText('Edit `foo.ts`')).toBeInTheDocument()
        })

        it('falls back to the wrench when mounted without a resolved icon', () => {
            const { container } = render(
                <FallbackMcpToolRenderer message={makeMessage({ title: 'Tool call' })} isLastInGroup />
            )
            // No sentinel icon was passed, so the header's icon slot holds the hard-coded wrench svg.
            const iconSlot = container.querySelector('.text-base.flex.items-center')
            expect(iconSlot).not.toBeNull()
            expect(iconSlot?.querySelector('svg')).toBeInTheDocument()
        })
    })
})
