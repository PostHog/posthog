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

export type NotebookArtifactApplyMode = 'replace' | 'insert-after-chat'

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
        chatId?: string,
        mode?: NotebookArtifactApplyMode
    ) => void
}

export const MarkdownNotebookRuntimeContext = createContext<MarkdownNotebookRuntimeContextValue | null>(null)

export function getNotebookAIChatUIContext({
    notebookShortId,
    notebookTitle,
    markdown,
    chatId,
    chatMarker = getNotebookAIChatMarker(chatId),
}: {
    notebookShortId: string | null
    notebookTitle: string
    markdown: string
    chatId: string
    chatMarker?: string
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
                insertion_placeholder_block_id: chatId,
                insertion_placeholder_marker: chatMarker,
            },
        ],
    }
}

export function preserveNotebookAIChatMarker(
    nextMarkdown: string,
    currentMarkdown: string,
    chatId: string | undefined
): string {
    if (!chatId) {
        return nextMarkdown
    }

    const chatMarker = getNotebookAIChatMarker(chatId)
    if (!currentMarkdown.includes(chatMarker) || nextMarkdown.includes(chatMarker)) {
        return nextMarkdown
    }

    return [nextMarkdown.trimEnd(), chatMarker].filter((block) => block.trim()).join('\n\n')
}

export function insertMarkdownAfterNotebookAIChatMarker(
    blockMarkdown: string,
    currentMarkdown: string,
    chatId: string | undefined
): string {
    const trimmedBlockMarkdown = blockMarkdown.trim()
    if (!trimmedBlockMarkdown || currentMarkdown.includes(trimmedBlockMarkdown)) {
        return currentMarkdown
    }

    if (!chatId) {
        return [currentMarkdown, trimmedBlockMarkdown].filter((block) => block.trim()).join('\n\n')
    }

    const chatMarker = getNotebookAIChatMarker(chatId)
    const chatMarkerIndex = currentMarkdown.indexOf(chatMarker)
    if (chatMarkerIndex === -1) {
        return [currentMarkdown, trimmedBlockMarkdown].filter((block) => block.trim()).join('\n\n')
    }

    const insertionIndex = chatMarkerIndex + chatMarker.length
    const beforeInsertion = currentMarkdown.slice(0, insertionIndex).trimEnd()
    const afterInsertion = currentMarkdown.slice(insertionIndex).trimStart()

    return [beforeInsertion, trimmedBlockMarkdown, afterInsertion].filter((block) => block.trim()).join('\n\n')
}

export function getNotebookAIChatMarker(chatId: string): string {
    return `<Chat id="${chatId}" />`
}

export function getInlineNotebookAIPanelId(chatId: string, mode: 'inline' | 'full'): string {
    return `notebook-inline-${mode}-${chatId}`
}
