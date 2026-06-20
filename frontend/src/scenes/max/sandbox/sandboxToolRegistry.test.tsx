import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import type { SandboxToolCallMessage } from '../maxTypes'
import { SandboxToolCall } from './components/tool/SandboxToolCall'
import { lookupSandboxToolRenderer, sandboxToolRegistry } from './sandboxToolRegistry'

function makeMessage(overrides: Partial<SandboxToolCallMessage> = {}): SandboxToolCallMessage {
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

describe('sandboxToolRegistry', () => {
    // Renderers are lazy() chunks, so entry.Renderer is an opaque LazyExoticComponent — assert on the
    // stable metadata (key → displayName/icon) the registry contributes, not on renderer identity.
    const dataToolCases: [string, string][] = [
        ['insight-create', 'Insight'],
        ['insight-update', 'Insight'],
        ['insight-get', 'Insight'],
        ['create_insight', 'Insight'],
        ['dashboard-create', 'Dashboard'],
        ['dashboard-update', 'Dashboard'],
        ['upsert_dashboard', 'Dashboard'],
        ['query-session-recordings-list', 'Session recordings'],
        ['search_session_recordings', 'Session recordings'],
        ['filter_session_recordings', 'Session recordings'],
        ['query-error-tracking-issues-list', 'Error tracking'],
        ['search_error_tracking_issues', 'Error tracking'],
        ['filter_error_tracking_issues', 'Error tracking'],
        ['query-trends', 'Trends query'],
        ['query-funnel', 'Funnel query'],
        ['notebooks-create', 'Notebook'],
        ['notebook-edit', 'Notebook'],
    ]

    it.each(dataToolCases)('resolves %s to a registered entry with displayName "%s"', (key, displayName) => {
        const entry = sandboxToolRegistry.lookup(key)
        expect(entry).not.toBeNull()
        expect(entry?.displayName).toEqual(displayName)
        expect(lookupSandboxToolRenderer(key).displayName).toEqual(displayName)
    })

    it('leaves unknown / unregistered tool names unregistered, resolving to the key as displayName', () => {
        expect(sandboxToolRegistry.lookup('mcp__user-installed__something')).toBeNull()
        // The synthesized fallback uses the resolved key as its displayName.
        expect(lookupSandboxToolRenderer('mcp__user-installed__something').displayName).toEqual(
            'mcp__user-installed__something'
        )
        expect(lookupSandboxToolRenderer('experiment-create').displayName).toEqual('experiment-create')
        expect(sandboxToolRegistry.lookup('insight-query')).toBeNull()
        expect(sandboxToolRegistry.lookup('read_insight')).toBeNull()
        expect(sandboxToolRegistry.lookup('query-llm-trace')).toBeNull()
    })

    // Claude built-ins are keyed by their stable SDK name; the registry contributes a friendly
    // displayName + icon (not the wrench fallback's key/wrench).
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
        ['TodoWrite', 'Tasks'],
        ['Skill', 'Skill'],
        ['ToolSearch', 'Tool search'],
        ['ExitPlanMode', 'Plan'],
        ['AskUserQuestion', 'Question'],
    ]

    it.each(builtinCases)('resolves built-in %s to a registered entry with displayName "%s"', (key, displayName) => {
        const entry = sandboxToolRegistry.lookup(key)
        expect(entry).not.toBeNull()
        expect(entry?.displayName).toEqual(displayName)
        expect(lookupSandboxToolRenderer(key).displayName).toEqual(displayName)
    })

    // PostHog single-exec discovery verbs are keyed by their sentinel key (from `resolveToolKey`); the
    // registry gives each a fitting icon + displayName instead of the wrench fallback.
    const execVerbCases: [string, string][] = [
        ['__posthog_exec_tools__', 'List tools'],
        ['__posthog_exec_search__', 'Search tools'],
        ['__posthog_exec_info__', 'Read tool'],
        ['__posthog_exec_schema__', 'Inspect schema'],
        ['__posthog_exec_unknown__', 'Run command'],
    ]

    it.each(execVerbCases)('resolves exec verb %s to a registered entry with displayName "%s"', (key, displayName) => {
        const entry = sandboxToolRegistry.lookup(key)
        expect(entry).not.toBeNull()
        expect(entry?.displayName).toEqual(displayName)
        expect(lookupSandboxToolRenderer(key).displayName).toEqual(displayName)
    })

    it('falls back to the wrench card (key as displayName) for an unmapped built-in-looking name', () => {
        expect(sandboxToolRegistry.lookup('NotARealTool')).toBeNull()
        expect(lookupSandboxToolRenderer('NotARealTool').displayName).toEqual('NotARealTool')
    })

    // Render-level: SandboxToolCall resolves the entry, loads the lazy renderer behind a Suspense
    // skeleton, and the resolved renderer reaches the screen. The skeleton shows the displayName first.
    describe('lazy dispatch', () => {
        it('renders a Bash call through its dedicated card once the chunk loads', async () => {
            render(
                <SandboxToolCall
                    message={makeMessage({
                        resolvedKey: 'Bash',
                        claudeToolName: 'Bash',
                        rawInput: { command: 'echo hello-bash' },
                    })}
                />
            )
            // Skeleton first (registry displayName), then the resolved card with the command. The
            // generous timeout covers jest compiling the lazy chunk's heavy deps on first load.
            expect(screen.getByText('Terminal')).toBeInTheDocument()
            expect(await screen.findByText('echo hello-bash', {}, { timeout: 10000 })).toBeInTheDocument()
        })

        it('renders an unmapped MCP tool through the generic card', async () => {
            render(
                <SandboxToolCall
                    message={makeMessage({
                        resolvedKey: 'do_thing',
                        rawServerName: 'user-mcp',
                        rawToolName: 'do_thing',
                    })}
                />
            )
            expect(await screen.findByText('(MCP)', {}, { timeout: 10000 })).toBeInTheDocument()
            expect(screen.getByText('do_thing')).toBeInTheDocument()
        })
    })
})
