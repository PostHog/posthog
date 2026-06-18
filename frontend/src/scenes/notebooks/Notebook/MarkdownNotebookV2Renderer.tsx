import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { MarkdownNotebook, parseMarkdownNotebook } from 'lib/components/MarkdownNotebook'
import type { MarkdownNotebookAskAIRequest } from 'lib/components/MarkdownNotebook'
import {
    insertNotebookAIFollowUpPromptAfterResponse,
    replaceNotebookAIResponseMarkdown,
} from 'lib/components/MarkdownNotebook/notebookAI'
import type { RemoteNotebookCaret } from 'lib/components/MarkdownNotebook/remoteCarets'
import { uuid } from 'lib/utils/dom'

import type { NotebookArtifactContent } from '~/queries/schema/schema-assistant-messages'

import { InlineAIAssistantMessage, InlineAICompletion, InlineNotebookAIRunner } from './MarkdownNotebookAIChat'
import { NOTEBOOK_MARKDOWN_REGISTRY } from './markdownNotebookRegistry'
import {
    InlineNotebookAIRequest,
    MarkdownNotebookRuntimeContext,
    MarkdownNotebookRuntimeContextValue,
    NotebookArtifactApplyMode,
    getInlineNotebookAIPanelId,
    getNotebookAIChatUIContext,
} from './markdownNotebookRuntime'
import { getMarkdownNotebookMarkdown, notebookArtifactContentToMarkdown } from './markdownNotebookV2'
import { notebookLogic } from './notebookLogic'

const NOTEBOOK_AI_FOLLOW_UP_PROMPT_MARKDOWN = '<Prompt question="" />'

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
    const markdownEditorValueRef = useRef(markdownEditorValue)
    const inlineAIResponseNodeCountsRef = useRef<Record<string, number>>({})
    const inlineAIResponseNodeIndicesRef = useRef<Record<string, number>>({})
    const [focusAIPromptRequest, setFocusAIPromptRequest] = useState<number | undefined>(undefined)

    useEffect(() => {
        markdownEditorValueRef.current = markdownEditorValue
    }, [markdownEditorValue])

    const updateMarkdownEditorValue = useCallback(
        (updater: (markdown: string) => string): void => {
            const currentMarkdown = markdownEditorValueRef.current
            const nextMarkdown = updater(currentMarkdown)
            if (nextMarkdown === currentMarkdown) {
                return
            }
            markdownEditorValueRef.current = nextMarkdown
            handleMarkdownEditorChange(nextMarkdown)
        },
        [handleMarkdownEditorChange]
    )

    const remoteCarets = useMemo<RemoteNotebookCaret[]>(() => [...markdownRemoteCarets], [markdownRemoteCarets])

    const handleAskAI = useCallback(
        ({
            chatId,
            query,
            source,
            responseNodeId,
            responseNodeIndex,
            responseMarker,
            markdown,
            markdownWithResponse,
            selectedMarkdown,
            selectedRefId,
        }: MarkdownNotebookAskAIRequest): void => {
            const uiContext = getNotebookAIChatUIContext({
                notebookShortId: notebook?.short_id ?? null,
                notebookTitle: notebook?.title ?? 'Untitled notebook',
                markdown: markdownWithResponse,
                chatId,
                chatMarker: responseMarker,
            })

            const inlineAIRequest: InlineNotebookAIRequest = {
                chatId,
                panelId: getInlineNotebookAIPanelId(chatId, 'inline'),
                query,
                source,
                responseNodeId,
                responseNodeIndex,
                responseMarker,
                markdown,
                markdownWithResponse,
                selectedMarkdown,
                selectedRefId,
                uiContext,
            }
            setInlineAIRequests((currentRequests) => [
                ...currentRequests.filter((currentRequest) => currentRequest.chatId !== chatId),
                inlineAIRequest,
            ])
            inlineAIResponseNodeCountsRef.current[chatId] = 1
            inlineAIResponseNodeIndicesRef.current[chatId] = responseNodeIndex
        },
        [notebook?.short_id, notebook?.title]
    )

    const getInlineAIRequest = useCallback(
        (chatId: string | undefined): InlineNotebookAIRequest | null => {
            if (!chatId) {
                return null
            }
            return inlineAIRequests.find((request) => request.chatId === chatId) ?? null
        },
        [inlineAIRequests]
    )

    const applyNotebookArtifactContent = useCallback(
        (content: NotebookArtifactContent, chatId?: string, mode: NotebookArtifactApplyMode = 'replace'): void => {
            const inlineAIRequest = getInlineAIRequest(chatId)
            if (inlineAIRequest) {
                const artifactMarkdown = notebookArtifactContentToMarkdown(content)
                const replacedNodeCount = inlineAIResponseNodeCountsRef.current[inlineAIRequest.chatId] ?? 1
                updateMarkdownEditorValue((currentMarkdown) => {
                    const result = replaceNotebookAIResponseMarkdown(
                        currentMarkdown,
                        getInlineAIResponseNodeIndex(inlineAIRequest, inlineAIResponseNodeIndicesRef.current),
                        artifactMarkdown,
                        replacedNodeCount
                    )
                    inlineAIResponseNodeIndicesRef.current[inlineAIRequest.chatId] = result.responseNodeIndex
                    return result.markdown
                })
                inlineAIResponseNodeCountsRef.current[inlineAIRequest.chatId] = getMarkdownBlockCount(artifactMarkdown)
                return
            }

            applyNotebookArtifactMarkdown(content, chatId, mode)
        },
        [applyNotebookArtifactMarkdown, getInlineAIRequest, updateMarkdownEditorValue]
    )

    const runtimeContext = useMemo<MarkdownNotebookRuntimeContextValue>(
        () => ({
            notebookShortId: notebook?.short_id ?? null,
            notebookTitle: notebook?.title ?? 'Untitled notebook',
            markdown: markdownEditorValue,
            applyNotebookArtifactContent,
        }),
        [applyNotebookArtifactContent, notebook?.short_id, notebook?.title, markdownEditorValue]
    )

    const handleInlineAIAssistantMessage = useCallback(
        (request: InlineNotebookAIRequest, message: InlineAIAssistantMessage): void => {
            if (message.hasArtifact) {
                return
            }

            const replacedNodeCount = inlineAIResponseNodeCountsRef.current[request.chatId] ?? 1
            updateMarkdownEditorValue((currentMarkdown) => {
                const result = replaceNotebookAIResponseMarkdown(
                    currentMarkdown,
                    getInlineAIResponseNodeIndex(request, inlineAIResponseNodeIndicesRef.current),
                    message.content,
                    replacedNodeCount
                )
                inlineAIResponseNodeIndicesRef.current[request.chatId] = result.responseNodeIndex
                return result.markdown
            })
            inlineAIResponseNodeCountsRef.current[request.chatId] = getMarkdownBlockCount(message.content)
        },
        [updateMarkdownEditorValue]
    )

    const handleInlineAIComplete = useCallback(
        (request: InlineNotebookAIRequest, completion: InlineAICompletion): void => {
            if (completion.kind !== 'assistant' && completion.kind !== 'artifact' && !completion.hasArtifact) {
                const replacedNodeCount = inlineAIResponseNodeCountsRef.current[request.chatId] ?? 1
                updateMarkdownEditorValue((currentMarkdown) => {
                    const result = replaceNotebookAIResponseMarkdown(
                        currentMarkdown,
                        getInlineAIResponseNodeIndex(request, inlineAIResponseNodeIndicesRef.current),
                        completion.message,
                        replacedNodeCount
                    )
                    inlineAIResponseNodeIndicesRef.current[request.chatId] = result.responseNodeIndex
                    return result.markdown
                })
                inlineAIResponseNodeCountsRef.current[request.chatId] = getMarkdownBlockCount(completion.message)
            }
            updateMarkdownEditorValue((currentMarkdown) =>
                insertNotebookAIFollowUpPromptAfterResponse(
                    currentMarkdown,
                    getInlineAIResponseNodeIndex(request, inlineAIResponseNodeIndicesRef.current),
                    NOTEBOOK_AI_FOLLOW_UP_PROMPT_MARKDOWN
                )
            )
            setFocusAIPromptRequest((currentRequest) => (currentRequest ?? 0) + 1)

            window.setTimeout(() => {
                delete inlineAIResponseNodeCountsRef.current[request.chatId]
                delete inlineAIResponseNodeIndicesRef.current[request.chatId]
                setInlineAIRequests((currentRequests) =>
                    currentRequests.filter((currentRequest) => currentRequest.chatId !== request.chatId)
                )
            }, 0)
        },
        [updateMarkdownEditorValue]
    )

    const handleInlineAIError = useCallback(
        (request: InlineNotebookAIRequest, completion: InlineAICompletion): void => {
            const replacedNodeCount = inlineAIResponseNodeCountsRef.current[request.chatId] ?? 1
            updateMarkdownEditorValue((currentMarkdown) => {
                const result = replaceNotebookAIResponseMarkdown(
                    currentMarkdown,
                    getInlineAIResponseNodeIndex(request, inlineAIResponseNodeIndicesRef.current),
                    completion.message,
                    replacedNodeCount
                )
                inlineAIResponseNodeIndicesRef.current[request.chatId] = result.responseNodeIndex
                return result.markdown
            })

            delete inlineAIResponseNodeCountsRef.current[request.chatId]
            delete inlineAIResponseNodeIndicesRef.current[request.chatId]
            setInlineAIRequests((currentRequests) =>
                currentRequests.filter((currentRequest) => currentRequest.chatId !== request.chatId)
            )
        },
        [updateMarkdownEditorValue]
    )

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
                remoteCarets={remoteCarets}
                onCaretChange={isEditable ? publishMarkdownCaret : undefined}
                onAskAI={isEditable ? handleAskAI : undefined}
                createAIChatId={uuid}
                deferRemoteValue={markdownEditorInteractionActive}
                onInteractionStateChange={setMarkdownEditorInteractionActive}
                className="Notebook__markdown-v2"
                data-attr="notebook-markdown-v2"
                autoFocus={isEditable}
                showDebug={isEditable}
                focusAIPromptRequest={focusAIPromptRequest}
            />
            {inlineAIRequests.map((request) => (
                <InlineNotebookAIRunner
                    key={request.chatId}
                    request={request}
                    onComplete={handleInlineAIComplete}
                    onError={handleInlineAIError}
                    onAssistantMessage={handleInlineAIAssistantMessage}
                />
            ))}
        </MarkdownNotebookRuntimeContext.Provider>
    )
}

function getMarkdownBlockCount(markdown: string): number {
    return Math.max(1, parseMarkdownNotebook(markdown).nodes.length)
}

function getInlineAIResponseNodeIndex(
    request: InlineNotebookAIRequest,
    responseNodeIndices: Record<string, number>
): number {
    return responseNodeIndices[request.chatId] ?? request.responseNodeIndex
}
