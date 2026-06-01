import { DocumentBlock } from '~/queries/schema/schema-assistant-artifacts'
import { ArtifactContentType, NotebookArtifactContent } from '~/queries/schema/schema-assistant-messages'

import type { MessageStatus } from '../../maxThreadLogic'
import type { McpToolRendererProps } from '../../mcpToolRegistry'
import { FallbackMcpToolRenderer } from '../FallbackMcpToolRenderer'
import { NotebookArtifactAnswer } from '../NotebookArtifactAnswer'

/** Registry key — the `notebooks-create` inner tool name parsed out of `exec`'s `call` verb (03_RICH_UI.md § 2.2). */
export const CREATE_NOTEBOOK_TOOL_KEY = 'notebooks-create'

/** Maps the ACP tool-call status onto the `MessageStatus` `NotebookArtifactAnswer` expects. */
function mapStatus(status: McpToolRendererProps['message']['status']): MessageStatus {
    if (status === 'completed') {
        return 'completed'
    }
    if (status === 'failed') {
        return 'error'
    }
    return 'loading'
}

/**
 * Extracts `NotebookArtifactContent` from the `notebooks-create` MCP tool output.
 *
 * v1 renders the whole document once the tool completes — the backend delivers
 * `rawOutput: { blocks, title, artifact_id }` in a single shot. Block-by-block streaming is
 * deferred (see TODO.md "Notebook block streaming"); `NotebookArtifactAnswer` already supports
 * incremental `blocks`, so the future switch is wire-format only.
 */
function extractNotebookContent(message: McpToolRendererProps['message']): NotebookArtifactContent | null {
    const rawOutput = message.rawOutput
    if (!rawOutput || typeof rawOutput !== 'object') {
        return null
    }

    const { blocks, title } = rawOutput as { blocks?: unknown; title?: unknown }
    if (!Array.isArray(blocks)) {
        return null
    }

    return {
        content_type: ArtifactContentType.Notebook,
        blocks: blocks as DocumentBlock[],
        title: typeof title === 'string' ? title : null,
    }
}

/**
 * Adapter for the `notebooks-create` MCP inner tool. Maps the tool's raw output onto the existing
 * `NotebookArtifactAnswer` props without modifying that component. Registered in `mcpToolRegistry`
 * under the inner tool's qualified name. See docs/internal/posthog-ai-migration/03_RICH_UI.md § 3.3.
 */
export function CreateNotebookAdapter({ message, isLastInGroup }: McpToolRendererProps): JSX.Element | null {
    const content = extractNotebookContent(message)
    if (!content) {
        // No usable notebook payload yet (still running, or malformed) — show the generic tool card.
        return <FallbackMcpToolRenderer message={message} isLastInGroup={isLastInGroup} />
    }

    return <NotebookArtifactAnswer content={content} status={mapStatus(message.status)} artifactId={message.id} />
}
