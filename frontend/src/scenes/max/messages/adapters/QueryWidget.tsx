import type { McpToolRendererProps } from '../../mcpToolRegistry'
import { FallbackMcpToolRenderer } from '../FallbackMcpToolRenderer'
import { VisualizationWidget } from '../VisualizationWidget'
import { extractQueryResult } from './extractors'

/**
 * Renders the MCP query-wrapper tools (query-trends, query-funnel, ...) through
 * `VisualizationWidget` as inline ephemeral visualizations. Pending calls and outputs without an
 * inline renderer fall back to the generic card.
 */
export function QueryWidget(props: McpToolRendererProps): JSX.Element {
    const { message } = props
    const result = message.status === 'completed' ? extractQueryResult(message) : null

    if (!result) {
        return <FallbackMcpToolRenderer {...props} />
    }

    return <VisualizationWidget content={result.content} openUrl={result.url} openTooltip="Open as insight" />
}
