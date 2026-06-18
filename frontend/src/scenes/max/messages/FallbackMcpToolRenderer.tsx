import { SandboxToolActivity, contentBlockText, renderContentBlocks } from '../components/Activity'
import type { McpToolRendererProps } from '../mcpToolRegistry'

export { contentBlockText, renderContentBlocks }

/**
 * Catch-all renderer for any MCP tool call not yet wired through a custom adapter — user-installed
 * MCPs, unknown inner tools, malformed `exec` commands. Renders a generic, greppable tool card so
 * the registry can ship incrementally.
 */
export function FallbackMcpToolRenderer({ message, icon, displayName }: McpToolRendererProps): JSX.Element {
    return <SandboxToolActivity message={message} icon={icon} displayName={displayName} />
}
