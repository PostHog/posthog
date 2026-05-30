import type { McpToolRendererProps } from '../../mcpToolRegistry'
import { VisualizationArtifactAnswer } from '../VisualizationArtifactAnswer'
import { extractVisualizationArtifact, isCompleted } from './extractors'
import { FallbackMcpToolRenderer } from './FallbackMcpToolRenderer'

/**
 * Renders the insight tools (`insight-create` / `insight-update` / `insight-query`) via the
 * existing `VisualizationArtifactAnswer`. `artifact_id` discriminates a saved insight from an
 * ephemeral query (handled in `extractVisualizationArtifact`). The contextual-edit flow is
 * dead, so `isEditingInsight` / `activeTabId` / `activeSceneId` collapse to false / null.
 * See docs/internal/posthog-ai-migration/03_RICH_UI.md §3.3 Example A.
 */
export function CreateInsightAdapter(props: McpToolRendererProps): JSX.Element | null {
    const artifact = extractVisualizationArtifact(props.message)
    // VisualizationArtifactAnswer renders nothing while loading, so show the running/pending card
    // until the tool completes — otherwise a running insight tool renders blank.
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
