import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { getSeriesColor } from 'lib/colors'
import { MarkdownNotebook, parseMarkdownNotebook } from 'lib/components/MarkdownNotebook'
import type { MarkdownNotebookAskAIRequest } from 'lib/components/MarkdownNotebook'
import {
    NOTEBOOK_AI_AGENT_ID,
    appendNotebookAgentCommentReplyToMarkdown,
    applyNotebookAgentArtifactMarkdown,
    getNotebookAgentClientId,
    getNotebookAgentColorIndex,
    getNotebookAgentsFromMarkdown,
    insertNotebookAIFollowUpPromptAfterCursor,
    insertNotebookAgentMarkdownAfterRef,
    replaceNotebookAIAgentCursorMarkdown,
    removeNotebookAgentFromMarkdown,
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

const NOTEBOOK_AI_FOLLOW_UP_PROMPT_MARKDOWN = '<Prompt question="" />'
const NOTEBOOK_AI_AGENT_DEPARTURE_IDLE_MS = 5_000

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
    const activeInlineAIRequestIdsRef = useRef<Set<string>>(new Set())
    const aiAgentActivityVersionRef = useRef(0)
    const aiAgentDepartureTimeoutRef = useRef<number | null>(null)
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

    const clearAIAgentDepartureTimeout = useCallback((): void => {
        if (aiAgentDepartureTimeoutRef.current !== null) {
            window.clearTimeout(aiAgentDepartureTimeoutRef.current)
            aiAgentDepartureTimeoutRef.current = null
        }
    }, [])

    const scheduleAIAgentDeparture = useCallback((): void => {
        clearAIAgentDepartureTimeout()
        if (activeInlineAIRequestIdsRef.current.size > 0) {
            return
        }

        const scheduledActivityVersion = aiAgentActivityVersionRef.current
        aiAgentDepartureTimeoutRef.current = window.setTimeout(() => {
            aiAgentDepartureTimeoutRef.current = null
            if (
                scheduledActivityVersion !== aiAgentActivityVersionRef.current ||
                activeInlineAIRequestIdsRef.current.size > 0
            ) {
                return
            }

            updateMarkdownEditorValue((currentMarkdown) =>
                removeNotebookAgentFromMarkdown(currentMarkdown, NOTEBOOK_AI_AGENT_ID)
            )
        }, NOTEBOOK_AI_AGENT_DEPARTURE_IDLE_MS)
    }, [clearAIAgentDepartureTimeout, updateMarkdownEditorValue])

    const markAIAgentActive = useCallback(
        (chatId: string): void => {
            activeInlineAIRequestIdsRef.current.add(chatId)
            aiAgentActivityVersionRef.current += 1
            clearAIAgentDepartureTimeout()
        },
        [clearAIAgentDepartureTimeout]
    )

    const markAIAgentInactive = useCallback(
        (chatId: string): void => {
            activeInlineAIRequestIdsRef.current.delete(chatId)
            scheduleAIAgentDeparture()
        },
        [scheduleAIAgentDeparture]
    )

    useEffect(() => clearAIAgentDepartureTimeout, [clearAIAgentDepartureTimeout])

    const handleAskAI = useCallback(
        ({
            chatId,
            query,
            source,
            responseNodeId,
            responseMarker,
            markdown,
            markdownWithResponse,
            selectedMarkdown,
            selectedRefId,
            agent,
        }: MarkdownNotebookAskAIRequest): void => {
            markAIAgentActive(chatId)
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
                responseMarker,
                markdown,
                markdownWithResponse,
                selectedMarkdown,
                selectedRefId,
                agent,
                uiContext,
            }
            setInlineAIRequests((currentRequests) => [
                ...currentRequests.filter((currentRequest) => currentRequest.chatId !== chatId),
                inlineAIRequest,
            ])
            inlineAIResponseNodeCountsRef.current[chatId] = 1
        },
        [markAIAgentActive, notebook?.short_id, notebook?.title]
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
            const agentRequest = getAgentRequest(chatId)
            if (!agentRequest?.agent) {
                const inlineAIRequest = getInlineAIRequest(chatId)
                if (inlineAIRequest) {
                    const artifactMarkdown = notebookArtifactContentToMarkdown(content)
                    const replacedNodeCount = inlineAIResponseNodeCountsRef.current[inlineAIRequest.chatId] ?? 1
                    updateMarkdownEditorValue((currentMarkdown) =>
                        replaceNotebookAIAgentCursorMarkdown(currentMarkdown, artifactMarkdown, replacedNodeCount)
                    )
                    inlineAIResponseNodeCountsRef.current[inlineAIRequest.chatId] =
                        getMarkdownBlockCount(artifactMarkdown)
                    return
                }

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
        [applyNotebookArtifactMarkdown, getAgentRequest, getInlineAIRequest, updateMarkdownEditorValue]
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
                if (!message.hasArtifact) {
                    const replacedNodeCount = inlineAIResponseNodeCountsRef.current[request.chatId] ?? 1
                    updateMarkdownEditorValue((currentMarkdown) =>
                        replaceNotebookAIAgentCursorMarkdown(currentMarkdown, message.content, replacedNodeCount)
                    )
                    inlineAIResponseNodeCountsRef.current[request.chatId] = getMarkdownBlockCount(message.content)
                }
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
            if (request.source !== 'agent' || !request.agent) {
                if (completion.kind !== 'assistant' && completion.kind !== 'artifact' && !completion.hasArtifact) {
                    const replacedNodeCount = inlineAIResponseNodeCountsRef.current[request.chatId] ?? 1
                    updateMarkdownEditorValue((currentMarkdown) =>
                        replaceNotebookAIAgentCursorMarkdown(currentMarkdown, completion.message, replacedNodeCount)
                    )
                    inlineAIResponseNodeCountsRef.current[request.chatId] = getMarkdownBlockCount(completion.message)
                }
                updateMarkdownEditorValue((currentMarkdown) =>
                    insertNotebookAIFollowUpPromptAfterCursor(currentMarkdown, NOTEBOOK_AI_FOLLOW_UP_PROMPT_MARKDOWN)
                )
                setFocusAIPromptRequest((currentRequest) => (currentRequest ?? 0) + 1)
            } else if (completion.kind === 'assistant' && !completion.hasArtifact) {
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
                delete inlineAIResponseNodeCountsRef.current[request.chatId]
                markAIAgentInactive(request.chatId)
                setInlineAIRequests((currentRequests) =>
                    currentRequests.filter((currentRequest) => currentRequest.chatId !== request.chatId)
                )
            }, 0)
        },
        [markAIAgentInactive, updateMarkdownEditorValue]
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
            } else {
                const replacedNodeCount = inlineAIResponseNodeCountsRef.current[request.chatId] ?? 1
                updateMarkdownEditorValue((currentMarkdown) =>
                    replaceNotebookAIAgentCursorMarkdown(currentMarkdown, completion.message, replacedNodeCount)
                )
            }

            delete inlineAIResponseNodeCountsRef.current[request.chatId]
            markAIAgentInactive(request.chatId)
            setInlineAIRequests((currentRequests) =>
                currentRequests.filter((currentRequest) => currentRequest.chatId !== request.chatId)
            )
        },
        [markAIAgentInactive, updateMarkdownEditorValue]
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
