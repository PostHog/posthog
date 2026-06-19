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
    // Legacy chat tags accumulate props (lastAnswer, title) over time, so when callers do
    // use a Chat marker it must match the tag as it appears in the markdown the AI receives.
    chatMarker = findNotebookAIChatTag(markdown, chatId)?.tag ?? getNotebookAIChatMarker(chatId),
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

    const currentTag = findNotebookAIChatTag(currentMarkdown, chatId)
    if (!currentTag) {
        return nextMarkdown
    }

    const nextTag = findNotebookAIChatTag(nextMarkdown, chatId)
    if (nextTag) {
        // The AI usually echoes the bare marker it was shown; the editor owns the tag's
        // runtime props (lastAnswer, title), so the current tag replaces whatever came back.
        if (nextTag.tag === currentTag.tag) {
            return nextMarkdown
        }
        return (
            nextMarkdown.slice(0, nextTag.index) +
            currentTag.tag +
            nextMarkdown.slice(nextTag.index + nextTag.tag.length)
        )
    }

    // The AI dropped the chat marker: re-anchor it at its previous position — right after the block
    // that preceded it — so the chat does not jump to the bottom of the notebook.
    const beforeMarker = currentMarkdown.slice(0, currentTag.index).trimEnd()
    if (!beforeMarker) {
        return [currentTag.tag, nextMarkdown.trimStart()].filter((block) => block.trim()).join('\n\n')
    }

    const lastBlockBreakIndex = beforeMarker.lastIndexOf('\n\n')
    const precedingBlock = (
        lastBlockBreakIndex === -1 ? beforeMarker : beforeMarker.slice(lastBlockBreakIndex + 2)
    ).trim()
    const anchorIndex = precedingBlock ? nextMarkdown.indexOf(precedingBlock) : -1
    if (anchorIndex !== -1) {
        const insertionIndex = anchorIndex + precedingBlock.length
        const beforeInsertion = nextMarkdown.slice(0, insertionIndex).trimEnd()
        const afterInsertion = nextMarkdown.slice(insertionIndex).trimStart()
        return [beforeInsertion, currentTag.tag, afterInsertion].filter((block) => block.trim()).join('\n\n')
    }

    return [nextMarkdown.trimEnd(), currentTag.tag].filter((block) => block.trim()).join('\n\n')
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

    const chatTag = chatId ? findNotebookAIChatTag(currentMarkdown, chatId) : null
    if (!chatTag) {
        return [currentMarkdown, trimmedBlockMarkdown].filter((block) => block.trim()).join('\n\n')
    }

    const insertionIndex = chatTag.index + chatTag.tag.length
    const beforeInsertion = currentMarkdown.slice(0, insertionIndex).trimEnd()
    const afterInsertion = currentMarkdown.slice(insertionIndex).trimStart()

    return [beforeInsertion, trimmedBlockMarkdown, afterInsertion].filter((block) => block.trim()).join('\n\n')
}

export function getNotebookAIChatMarker(chatId: string): string {
    return `<Chat id="${chatId}" />`
}

/**
 * Locate this chat's tag in the markdown, tolerating the props the editor accumulates on
 * it over time (`<Chat id="x" lastAnswer="…" />`) — a bare-marker `indexOf` stops matching
 * after the first streamed answer.
 */
export function findNotebookAIChatTag(markdown: string, chatId: string): { index: number; tag: string } | null {
    const escapedChatId = chatId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const match = markdown.match(new RegExp(`<Chat\\b[^>]*\\bid="${escapedChatId}"[^>]*/>`))
    if (!match || match.index === undefined) {
        return null
    }
    return { index: match.index, tag: match[0] }
}

export function getInlineNotebookAIPanelId(chatId: string, mode: 'inline' | 'full'): string {
    return `notebook-inline-${mode}-${chatId}`
}
