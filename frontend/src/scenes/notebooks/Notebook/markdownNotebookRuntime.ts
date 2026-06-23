import { createContext } from 'react'

import type { MarkdownNotebookAskAIRequest } from 'lib/components/MarkdownNotebook'
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
                markdown_with_insertion_placeholder: markdown,
                insertion_placeholder_block_id: conversationId,
                insertion_placeholder_marker: responseMarker,
            },
        ],
    }
}

export function getInlineNotebookAIPanelId(conversationId: string, mode: 'inline' | 'full'): string {
    return `notebook-inline-${mode}-${conversationId}`
}
