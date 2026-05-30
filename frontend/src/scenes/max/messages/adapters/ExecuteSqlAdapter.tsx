import {
    ArtifactContentType,
    ArtifactMessage,
    ArtifactSource,
    AssistantMessageType,
    VisualizationArtifactContent,
} from '~/queries/schema/schema-assistant-messages'
import { NodeKind } from '~/queries/schema/schema-general'

import type { McpToolRendererProps } from '../../mcpToolRegistry'
import { VisualizationArtifactAnswer } from '../VisualizationArtifactAnswer'
import { isCompleted, toolInput } from './extractors'
import { FallbackMcpToolRenderer } from './FallbackMcpToolRenderer'

/**
 * Renders `execute-sql`. The input carries a HogQL `query` string; we wrap it in a
 * `DataVisualizationNode`-backed artifact so the existing `Query` shell renders the result
 * table (mirroring today's `executedSQLQuery` snippet in `AssistantActionComponent`). When
 * there is no SQL query string the call is non-tabular (e.g. a DDL/echo) — fall through to
 * the generic card, which prints the `content[]` text frames.
 * See docs/internal/posthog-ai-migration/03_RICH_UI.md §4.
 */
export function ExecuteSqlAdapter(props: McpToolRendererProps): JSX.Element | null {
    const input = toolInput(props.message)
    const sql = typeof input.query === 'string' ? input.query : null
    // `VisualizationArtifactAnswer` returns null while loading, leaving the row blank mid-run, so
    // fall through to the generic card until the SQL has actually executed.
    if (!sql || !isCompleted(props.message)) {
        return <FallbackMcpToolRenderer {...props} />
    }

    const content: VisualizationArtifactContent = {
        content_type: ArtifactContentType.Visualization,
        query: { kind: NodeKind.HogQLQuery, query: sql },
    }
    const envelope: ArtifactMessage = {
        type: AssistantMessageType.Artifact,
        id: props.message.id,
        artifact_id: '',
        source: ArtifactSource.State,
        content,
    }

    return (
        <VisualizationArtifactAnswer
            message={envelope}
            content={content}
            status="completed"
            isEditingInsight={false}
            activeTabId={null}
            activeSceneId={null}
        />
    )
}
