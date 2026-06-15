import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useState } from 'react'

import { MarkdownNotebook } from 'lib/components/MarkdownNotebook'
import type { MarkdownNotebookAskAIRequest } from 'lib/components/MarkdownNotebook'
import { uuid } from 'lib/utils'

import { InlineNotebookAIRunner } from './MarkdownNotebookAIChat'
import { NOTEBOOK_MARKDOWN_REGISTRY } from './markdownNotebookRegistry'
import {
    InlineNotebookAIRequest,
    MarkdownNotebookRuntimeContext,
    MarkdownNotebookRuntimeContextValue,
    getInlineNotebookAIPanelId,
    getNotebookAIChatUIContext,
} from './markdownNotebookRuntime'
import { getMarkdownNotebookMarkdown } from './markdownNotebookV2'
import { notebookLogic } from './notebookLogic'

export function MarkdownNotebookV2(): JSX.Element {
    const { isEditable, notebook, markdownEditorValue, markdownEditorInteractionActive, markdownRemoteCarets } =
        useValues(notebookLogic)
    const {
        handleMarkdownEditorChange,
        setMarkdownEditorInteractionActive,
        applyNotebookArtifactMarkdown,
        reportMarkdownMergeConflicts,
        publishMarkdownCaret,
    } = useActions(notebookLogic)
    const remoteMarkdown = getMarkdownNotebookMarkdown(notebook?.content)
    const [inlineAIRequests, setInlineAIRequests] = useState<InlineNotebookAIRequest[]>([])

    const handleAskAI = useCallback(
        ({
            chatId,
            query,
            source,
            chatNodeId,
            chatMarker,
            markdown,
            markdownWithChat,
            selectedMarkdown,
        }: MarkdownNotebookAskAIRequest): void => {
            const uiContext = getNotebookAIChatUIContext({
                notebookShortId: notebook?.short_id ?? null,
                notebookTitle: notebook?.title ?? 'Untitled notebook',
                markdown: markdownWithChat,
                chatId,
                chatMarker,
            })

            const inlineAIRequest: InlineNotebookAIRequest = {
                chatId,
                panelId: getInlineNotebookAIPanelId(chatId, 'inline'),
                query,
                source,
                chatNodeId,
                chatMarker,
                markdown,
                markdownWithChat,
                selectedMarkdown,
                uiContext,
            }
            setInlineAIRequests((currentRequests) => [
                ...currentRequests.filter((currentRequest) => currentRequest.chatId !== chatId),
                inlineAIRequest,
            ])
        },
        [notebook?.short_id, notebook?.title]
    )

    const runtimeContext = useMemo<MarkdownNotebookRuntimeContextValue>(
        () => ({
            notebookShortId: notebook?.short_id ?? null,
            notebookTitle: notebook?.title ?? 'Untitled notebook',
            markdown: markdownEditorValue,
            applyNotebookArtifactContent: applyNotebookArtifactMarkdown,
        }),
        [applyNotebookArtifactMarkdown, notebook?.short_id, notebook?.title, markdownEditorValue]
    )

    const handleInlineAIComplete = useCallback((request: InlineNotebookAIRequest): void => {
        window.setTimeout(() => {
            setInlineAIRequests((currentRequests) =>
                currentRequests.filter((currentRequest) => currentRequest.chatId !== request.chatId)
            )
        }, 0)
    }, [])

    const handleInlineAIError = useCallback((request: InlineNotebookAIRequest): void => {
        setInlineAIRequests((currentRequests) =>
            currentRequests.filter((currentRequest) => currentRequest.chatId !== request.chatId)
        )
    }, [])

    return (
        <MarkdownNotebookRuntimeContext.Provider value={runtimeContext}>
            <MarkdownNotebook
                value={markdownEditorValue}
                remoteValue={remoteMarkdown}
                remoteVersion={notebook?.version}
                mode={isEditable ? 'edit' : 'view'}
                registry={NOTEBOOK_MARKDOWN_REGISTRY}
                onChange={isEditable ? handleMarkdownEditorChange : undefined}
                onConflict={reportMarkdownMergeConflicts}
                remoteCarets={markdownRemoteCarets}
                onCaretChange={isEditable ? publishMarkdownCaret : undefined}
                onAskAI={isEditable ? handleAskAI : undefined}
                createAIChatId={uuid}
                deferRemoteValue={markdownEditorInteractionActive}
                onInteractionStateChange={setMarkdownEditorInteractionActive}
                className="Notebook__markdown-v2"
                data-attr="notebook-markdown-v2"
                autoFocus={isEditable}
                showDebug={isEditable}
            />
            {inlineAIRequests.map((request) => (
                <InlineNotebookAIRunner
                    key={request.chatId}
                    request={request}
                    onComplete={handleInlineAIComplete}
                    onError={handleInlineAIError}
                />
            ))}
        </MarkdownNotebookRuntimeContext.Provider>
    )
}
