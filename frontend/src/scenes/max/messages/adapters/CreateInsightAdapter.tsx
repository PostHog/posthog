import type { McpToolRendererProps } from '../../mcpToolRegistry'
import { FallbackMcpToolRenderer } from '../FallbackMcpToolRenderer'
import { VisualizationArtifactAnswer } from '../VisualizationArtifactAnswer'
import { extractVisualizationArtifact } from './extractors'

/**
 * Renders insight create / update / query / read tool calls through the existing
 * `VisualizationArtifactAnswer`. The contextual-edit flow is dead under the sandbox runtime, so
 * `isEditingInsight` / `activeTabId` / `activeSceneId` collapse to `false` / `null`. Until the
 * artifact lands (pending / in-progress / malformed output) we fall back to the generic card so
 * the call still renders something. See docs/internal/posthog-ai-migration/03_RICH_UI.md § 3.3.
 */
export function CreateInsightAdapter({ message, isLastInGroup }: McpToolRendererProps): JSX.Element {
    const artifact = message.status === 'completed' ? extractVisualizationArtifact(message) : null

    if (!artifact) {
        return <FallbackMcpToolRenderer message={message} isLastInGroup={isLastInGroup} />
    }

    return (
        <VisualizationArtifactAnswer
            message={{ ...artifact.envelope, status: 'completed' }}
            content={artifact.content}
            status="completed"
            isEditingInsight={false}
            activeTabId={null}
            activeSceneId={null}
        />
    )
}
