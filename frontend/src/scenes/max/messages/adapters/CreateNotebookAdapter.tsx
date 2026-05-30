import type { McpToolRendererProps } from '../../mcpToolRegistry'
import { NotebookArtifactAnswer } from '../NotebookArtifactAnswer'
import { extractNotebookContent, isCompleted } from './extractors'
import { FallbackMcpToolRenderer } from './FallbackMcpToolRenderer'

/**
 * Renders the `notebooks-create` tool (plural slug — the real generated name) via the existing
 * `NotebookArtifactAnswer`, unchanged. `extractNotebookContent` maps the tool's `rawOutput` to a
 * `NotebookArtifactContent` ({ blocks, title }) plus the saved notebook's `artifactId`.
 *
 * v1 is batch-only: the whole notebook renders on completion. `NotebookArtifactAnswer` already
 * handles incremental blocks, so enabling block-by-block streaming later is a wire-only switch.
 * Falls through to the generic card when no blocks are present.
 * See docs/internal/posthog-ai-migration/03_RICH_UI.md §§3.3, 4.
 */
export function CreateNotebookAdapter(props: McpToolRendererProps): JSX.Element {
    const artifact = extractNotebookContent(props.message)
    if (!artifact) {
        return <FallbackMcpToolRenderer {...props} />
    }
    return (
        <NotebookArtifactAnswer
            content={artifact.content}
            status={isCompleted(props.message) ? 'completed' : 'loading'}
            artifactId={artifact.artifactId}
        />
    )
}
