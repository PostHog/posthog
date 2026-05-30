import type { McpToolRendererProps } from '../../mcpToolRegistry'
import { VisualizationArtifactAnswer } from '../VisualizationArtifactAnswer'
import { extractVisualizationArtifact, isCompleted } from './extractors'
import { FallbackMcpToolRenderer } from './FallbackMcpToolRenderer'

/**
 * Renders the typed query-wrapper tools (`query-trends` / `query-funnel` / `query-retention` /
 * `query-stickiness` / `query-paths` / `query-lifecycle` / `query-trends-actors` /
 * `query-lifecycle-actors` / `query-llm-trace` / `query-llm-traces-list`) — see
 * services/mcp/definitions/query-wrappers.yaml. These are always ephemeral (no saved
 * artifact); the typed query is rendered through the existing `Query` shell inside
 * `VisualizationArtifactAnswer`. See docs/internal/posthog-ai-migration/03_RICH_UI.md §4.
 */
export function QueryWrapperAdapter(props: McpToolRendererProps): JSX.Element | null {
    const artifact = extractVisualizationArtifact(props.message, ['query', 'source'])
    // VisualizationArtifactAnswer renders nothing while loading, so show the running/pending card
    // until the tool completes — otherwise a running query tool renders blank.
    if (!artifact || !isCompleted(props.message)) {
        return <FallbackMcpToolRenderer {...props} />
    }
    return (
        <VisualizationArtifactAnswer
            message={artifact.envelope}
            content={artifact.content}
            status="completed"
            isEditingInsight={false}
            activeTabId={null}
            activeSceneId={null}
        />
    )
}
