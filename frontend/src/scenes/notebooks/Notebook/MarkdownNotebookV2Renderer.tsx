import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { getSeriesColor } from 'lib/colors'
import { MarkdownNotebook } from 'lib/components/MarkdownNotebook'
import type { MarkdownNotebookAskAIRequest } from 'lib/components/MarkdownNotebook'
import {
    appendNotebookAgentCommentReplyToMarkdown,
    applyNotebookAgentArtifactMarkdown,
    getNotebookAgentClientId,
    getNotebookAgentColorIndex,
    getNotebookAgentsFromMarkdown,
    insertNotebookAgentMarkdownAfterRef,
} from 'lib/components/MarkdownNotebook/notebookAgents'
import type { RemoteNotebookCaret } from 'lib/components/MarkdownNotebook/remoteCarets'
import { uuid } from 'lib/utils'

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

    useEffect(() => {
        markdownEditorValueRef.current = markdownEditorValue
    }, [markdownEditorValue])

    const notebookAgents = useMemo(() => getNotebookAgentsFromMarkdown(markdownEditorValue), [markdownEditorValue])
    const agentCarets = useMemo<RemoteNotebookCaret[]>(
        () =>
            notebookAgents.map((agent) => ({
                clientId: getNotebookAgentClientId(agent),
                userName: agent.name,
                color: getSeriesColor(getNotebookAgentColorIndex(agent)),
                position: agent.cursor ?? { nodeIndex: 0, offset: 0 },
                version: notebook?.version,
                kind: 'agent',
                agentId: agent.id,
            })),
        [notebookAgents, notebook?.version]
    )
    const remoteCarets = useMemo<RemoteNotebookCaret[]>(
        () => [...markdownRemoteCarets, ...agentCarets],
        [agentCarets, markdownRemoteCarets]
    )

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
            agent,
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
                agent,
                uiContext,
            }
            setInlineAIRequests((currentRequests) => [
                ...currentRequests.filter((currentRequest) => currentRequest.chatId !== chatId),
                inlineAIRequest,
            ])
        },
        [notebook?.short_id, notebook?.title]
    )

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

    const getAgentRequest = useCallback(
        (chatId: string | undefined): InlineNotebookAIRequest | null => {
            if (!chatId) {
                return null
            }
            return (
                inlineAIRequests.find(
                    (request) => request.chatId === chatId && request.source === 'agent' && request.agent
                ) ?? null
            )
        },
        [inlineAIRequests]
    )

    const applyNotebookArtifactContent = useCallback(
        (content: NotebookArtifactContent, chatId?: string, mode: NotebookArtifactApplyMode = 'replace'): void => {
            const agentRequest = getAgentRequest(chatId)
            if (!agentRequest?.agent) {
                applyNotebookArtifactMarkdown(content, chatId, mode)
                return
            }

            const requestAgent = agentRequest.agent
            updateMarkdownEditorValue((currentMarkdown) => {
                if (!getNotebookAgentsFromMarkdown(currentMarkdown).some((agent) => agent.id === requestAgent.id)) {
                    return currentMarkdown
                }

                return applyNotebookAgentArtifactMarkdown({
                    markdown: currentMarkdown,
                    refId: requestAgent.refId,
                    artifactMarkdown: notebookArtifactContentToMarkdown(content),
                    replace: mode !== 'insert-after-chat',
                })
            })
        },
        [applyNotebookArtifactMarkdown, getAgentRequest, updateMarkdownEditorValue]
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
            if (request.source !== 'agent' || !request.agent) {
                return
            }

            const requestAgent = request.agent
            updateMarkdownEditorValue((currentMarkdown) => {
                if (!getNotebookAgentsFromMarkdown(currentMarkdown).some((agent) => agent.id === requestAgent.id)) {
                    return currentMarkdown
                }

                return appendNotebookAgentCommentReplyToMarkdown({
                    markdown: currentMarkdown,
                    refId: requestAgent.refId,
                    agent: requestAgent,
                    text: message.content,
                    replyId: message.id,
                })
            })
        },
        [updateMarkdownEditorValue]
    )

    const handleInlineAIComplete = useCallback(
        (request: InlineNotebookAIRequest, completion: InlineAICompletion): void => {
            if (
                request.source === 'agent' &&
                request.agent &&
                completion.kind === 'assistant' &&
                !completion.hasArtifact
            ) {
                const requestAgent = request.agent
                updateMarkdownEditorValue((currentMarkdown) => {
                    if (!getNotebookAgentsFromMarkdown(currentMarkdown).some((agent) => agent.id === requestAgent.id)) {
                        return currentMarkdown
                    }

                    return insertNotebookAgentMarkdownAfterRef({
                        markdown: currentMarkdown,
                        refId: requestAgent.refId,
                        insertedMarkdown: completion.message,
                    })
                })
            }

            window.setTimeout(() => {
                setInlineAIRequests((currentRequests) =>
                    currentRequests.filter((currentRequest) => currentRequest.chatId !== request.chatId)
                )
            }, 0)
        },
        [updateMarkdownEditorValue]
    )

    const handleInlineAIError = useCallback(
        (request: InlineNotebookAIRequest, completion: InlineAICompletion): void => {
            if (request.source === 'agent' && request.agent) {
                const requestAgent = request.agent
                updateMarkdownEditorValue((currentMarkdown) =>
                    appendNotebookAgentCommentReplyToMarkdown({
                        markdown: currentMarkdown,
                        refId: requestAgent.refId,
                        agent: requestAgent,
                        text: completion.message,
                        replyId: `${request.chatId}-error`,
                    })
                )
            }

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
