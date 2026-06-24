import { GenericMcpToolRenderer } from '../../sandbox/components/tool/GenericMcpToolRenderer'
import { SandboxDataToolRow } from '../../sandbox/components/tool/SandboxDataToolRow'
import type { SandboxToolRendererProps } from '../../sandbox/sandboxToolRegistry'
import { VisualizationWidget } from '../VisualizationWidget'
import { extractQueryResult } from './extractors'

/**
 * Renders the MCP query-wrapper tools (query-trends, query-funnel, ...) through
 * `VisualizationWidget` as inline ephemeral visualizations. Pending calls and outputs without an
 * inline renderer fall back to the generic card.
 */
export function QueryWidget(props: SandboxToolRendererProps): JSX.Element {
    const { message } = props
    const result = message.status === 'completed' ? extractQueryResult(message) : null

    if (!result) {
        return <GenericMcpToolRenderer {...props} />
    }

    return (
        <SandboxDataToolRow {...props}>
            <VisualizationWidget content={result.content} openUrl={result.url} openTooltip="Open as insight" embedded />
        </SandboxDataToolRow>
    )
}
