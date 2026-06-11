import type { ComponentType } from 'react'

import { IconNotebook, IconWrench } from '@posthog/icons'

import type { McpToolCallMessage } from './maxTypes'
import { CreateNotebookWidget } from './messages/adapters/CreateNotebookWidget'
import { FallbackMcpToolRenderer } from './messages/FallbackMcpToolRenderer'

export interface McpToolRendererProps {
    message: McpToolCallMessage
    isLastInGroup: boolean
}

export interface McpToolRegistryEntry {
    /**
     * Registry key. For single-exec PostHog tools, this is the **inner** tool name parsed from
     * `rawInput.command` (e.g. "execute-sql", "insight-create"); for `exec`'s discovery verbs,
     * the sentinel "__posthog_exec_tools__" etc.; for non-exec MCP tools and Claude built-ins,
     * the wire `toolName` directly (e.g. "TodoWrite", "WebSearch").
     */
    key: string
    /** Display name / icon for fallback rendering and for the tool-call header line. */
    displayName: string
    icon: JSX.Element
    Renderer: ComponentType<McpToolRendererProps>
}

export interface McpToolRegistry {
    register: (entry: McpToolRegistryEntry) => void
    lookup: (toolName: string) => McpToolRegistryEntry | null
}

class MapBackedRegistry implements McpToolRegistry {
    private entries = new Map<string, McpToolRegistryEntry>()

    register(entry: McpToolRegistryEntry): void {
        this.entries.set(entry.key, entry)
    }

    lookup(toolName: string): McpToolRegistryEntry | null {
        return this.entries.get(toolName) ?? null
    }
}

/**
 * Single module-level registry of MCP tool-name → renderer. All entries are registered at module
 * load — no dynamic registration, no hooks, no scene callbacks. Custom adapters are registered
 * per tool (behind `phai-sandbox-tool-{slug}` flags); any tool without one falls through to
 * `FallbackMcpToolRenderer`.
 */
export const mcpToolRegistry: McpToolRegistry = new MapBackedRegistry()

// Custom adapters are registered here as they land. The skeleton ships with the fallback only.

// --- Data tools: notebooks ---
// The generated CRUD tools and the handwritten notebook-edit (the collab-safe content editor)
// all return the same REST notebook payload.
for (const key of ['notebooks-create', 'notebooks-partial-update', 'notebooks-retrieve', 'notebook-edit']) {
    mcpToolRegistry.register({
        key,
        displayName: 'Notebook',
        icon: <IconNotebook />,
        Renderer: CreateNotebookWidget,
    })
}

/** Looks up the renderer entry for a resolved tool key, falling back to the generic card. */
export function lookupMcpToolRenderer(resolvedKey: string): McpToolRegistryEntry {
    return (
        mcpToolRegistry.lookup(resolvedKey) ?? {
            key: resolvedKey,
            displayName: resolvedKey,
            icon: <IconWrench />,
            Renderer: FallbackMcpToolRenderer,
        }
    )
}
