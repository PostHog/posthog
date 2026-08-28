import { createContext } from 'react'

import type { MarkdownNotebookAskAIRequest } from 'lib/components/MarkdownNotebook'
import { parseMarkdownNotebook, serializeMarkdownNotebook } from 'lib/components/MarkdownNotebook/markdown'
import type { NotebookBlockNode, NotebookPropValue } from 'lib/components/MarkdownNotebook/types'
import { ThreadMessage } from 'scenes/max/maxThreadLogic'
import { MaxContextType } from 'scenes/max/maxTypes'
import type { MaxUIContext } from 'scenes/max/maxTypes'

import {
    type ArtifactMessage,
    type NotebookArtifactContent,
    type VisualizationArtifactContent,
} from '~/queries/schema/schema-assistant-messages'

export type InlineNotebookAIRequest = MarkdownNotebookAskAIRequest & {
    panelId: string
    uiContext?: Partial<MaxUIContext>
}

export type NotebookApplicableArtifactContent = NotebookArtifactContent | VisualizationArtifactContent

export type NotebookApplicableArtifactThreadMessage = ArtifactMessage &
    ThreadMessage & {
        content: NotebookApplicableArtifactContent
    }

export type NotebookArtifactApplyMode = 'replace' | 'insert-after-response'

export type NotebookArtifactApplyRequest = {
    content: NotebookArtifactContent
    mode: NotebookArtifactApplyMode
}

export type MarkdownNotebookRuntimeContextValue = {
    notebookShortId: string | null
    notebookTitle: string
    markdown: string
    applyNotebookArtifactContent: (
        content: NotebookArtifactContent,
        conversationId?: string,
        mode?: NotebookArtifactApplyMode
    ) => void
}

export const MarkdownNotebookRuntimeContext = createContext<MarkdownNotebookRuntimeContextValue | null>(null)

const INLINE_NOTEBOOK_AI_CONTEXT_MAX_LENGTH = 100_000

function getNotebookPropObject(value: NotebookPropValue | undefined): Record<string, NotebookPropValue> | null {
    return value && typeof value === 'object' && !Array.isArray(value) ? value : null
}

function getInlineNotebookAIContextMarkdown(markdown: string): string {
    const document = parseMarkdownNotebook(markdown)
    let removedMedia = false
    const nodes = document.nodes.map((node): NotebookBlockNode => {
        if (node.type !== 'component') {
            return node
        }

        const result = getNotebookPropObject(node.props.result)
        if (!result || !Array.isArray(result.media) || result.media.length === 0) {
            return node
        }

        const { media: _media, ...resultWithoutMedia } = result
        removedMedia = true
        // The serializer re-emits `raw` verbatim when a node carries parse errors, which would
        // restore the media we just dropped. Discard `raw`/`errors` so serialization uses the props.
        const { raw: _raw, errors: _errors, ...nodeWithoutRaw } = node
        return {
            ...nodeWithoutRaw,
            props: {
                ...node.props,
                result: resultWithoutMedia,
            },
        }
    })
    const contextMarkdown = removedMedia ? serializeMarkdownNotebook({ ...document, nodes }) : markdown

    return contextMarkdown.slice(0, INLINE_NOTEBOOK_AI_CONTEXT_MAX_LENGTH)
}

export function getInlineNotebookAIUIContext({
    notebookShortId,
    notebookTitle,
    markdown,
    conversationId,
    responseMarker = 'Thinking...',
}: {
    notebookShortId: string | null
    notebookTitle: string
    markdown: string
    conversationId: string
    responseMarker?: string
}): Partial<MaxUIContext> | undefined {
    if (!notebookShortId) {
        return undefined
    }

    return {
        notebooks: [
            {
                type: MaxContextType.NOTEBOOK,
                id: notebookShortId,
                name: notebookTitle,
                markdown_with_insertion_placeholder: getInlineNotebookAIContextMarkdown(markdown),
                insertion_placeholder_block_id: conversationId,
                insertion_placeholder_marker: responseMarker,
            },
        ],
    }
}

export function getInlineNotebookAIPanelId(conversationId: string, mode: 'inline' | 'full'): string {
    return `notebook-inline-${mode}-${conversationId}`
}
