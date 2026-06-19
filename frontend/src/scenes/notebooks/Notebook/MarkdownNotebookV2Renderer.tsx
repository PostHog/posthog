import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconGraph } from '@posthog/icons'

import { MarkdownNotebook, parseMarkdownNotebook } from 'lib/components/MarkdownNotebook'
import type {
    InsertCommand,
    MarkdownNotebookAskAIRequest,
    MarkdownNotebookInsertMenuApi,
} from 'lib/components/MarkdownNotebook'
import {
    insertNotebookAIFollowUpPromptAfterResponse,
    replaceNotebookAIResponseMarkdown,
} from 'lib/components/MarkdownNotebook/notebookAI'
import type { MarkdownNotebookCaretPosition, RemoteNotebookCaret } from 'lib/components/MarkdownNotebook/remoteCarets'
import type { NotebookBlockNode } from 'lib/components/MarkdownNotebook/types'
import { getInlineText } from 'lib/components/MarkdownNotebook/utils'
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
import { MarkdownNotebookSavedInsightPicker } from './MarkdownNotebookSavedInsightPicker'
import { getMarkdownNotebookMarkdown, notebookArtifactContentToMarkdown } from './markdownNotebookV2'
import { notebookLogic } from './notebookLogic'
import {
    NOTEBOOK_AI_PRESENCE_COLOR,
    NOTEBOOK_AI_PRESENCE_CLIENT_ID,
    NOTEBOOK_AI_PRESENCE_NAME,
} from './notebookPresence'

const NOTEBOOK_AI_FOLLOW_UP_PROMPT_MARKDOWN = '<Prompt question="" />'
const NOTEBOOK_AI_PRESENCE_DEPARTURE_IDLE_MS = 5_000
const NOTEBOOK_AI_PRESENCE_FADE_OUT_MS = 300

export function MarkdownNotebookV2(): JSX.Element {
    const { isEditable, notebook, markdownEditorValue, markdownEditorInteractionActive, markdownRemoteCarets } =
        useValues(notebookLogic)
    const {
        handleMarkdownEditorChange,
        setMarkdownEditorInteractionActive,
        applyNotebookArtifactMarkdown,
        reportMarkdownMergeConflicts,
        publishMarkdownCaret,
        setMarkdownAIPresenceActive,
    } = useActions(notebookLogic)
    const remoteMarkdown = getMarkdownNotebookMarkdown(notebook?.content)
    const [inlineAIRequests, setInlineAIRequests] = useState<InlineNotebookAIRequest[]>([])
    const [aiCaretPosition, setAICaretPosition] = useState<MarkdownNotebookCaretPosition | null>(null)
    const [aiCaretFading, setAICaretFading] = useState(false)
    const markdownEditorValueRef = useRef(markdownEditorValue)
    const inlineAIResponseNodeCountsRef = useRef<Record<string, number>>({})
    const inlineAIResponseNodeIndicesRef = useRef<Record<string, number>>({})
    const activeInlineAIRequestIdsRef = useRef<Set<string>>(new Set())
    const aiPresenceRetainedByPromptRef = useRef(false)
    const aiPresenceActivityVersionRef = useRef(0)
    const aiPresenceDepartureTimeoutRef = useRef<number | null>(null)
    const aiPresenceFadeTimeoutRef = useRef<number | null>(null)
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

    const clearAIPresenceDepartureTimeout = useCallback((): void => {
        if (aiPresenceDepartureTimeoutRef.current !== null) {
            window.clearTimeout(aiPresenceDepartureTimeoutRef.current)
            aiPresenceDepartureTimeoutRef.current = null
        }
    }, [])

    const clearAIPresenceFadeTimeout = useCallback((): void => {
        if (aiPresenceFadeTimeoutRef.current !== null) {
            window.clearTimeout(aiPresenceFadeTimeoutRef.current)
            aiPresenceFadeTimeoutRef.current = null
        }
    }, [])

    const clearAIPresenceTimeouts = useCallback((): void => {
        clearAIPresenceDepartureTimeout()
        clearAIPresenceFadeTimeout()
    }, [clearAIPresenceDepartureTimeout, clearAIPresenceFadeTimeout])

    const finishAIPresenceDeparture = useCallback(
        (scheduledActivityVersion: number): void => {
            if (
                scheduledActivityVersion !== aiPresenceActivityVersionRef.current ||
                activeInlineAIRequestIdsRef.current.size > 0 ||
                aiPresenceRetainedByPromptRef.current
            ) {
                setAICaretFading(false)
                return
            }

            setAICaretPosition(null)
            setAICaretFading(false)
            setMarkdownAIPresenceActive(false)
        },
        [setMarkdownAIPresenceActive]
    )

    const scheduleAIPresenceDeparture = useCallback((): void => {
        clearAIPresenceTimeouts()
        if (activeInlineAIRequestIdsRef.current.size > 0 || aiPresenceRetainedByPromptRef.current) {
            return
        }

        const scheduledActivityVersion = aiPresenceActivityVersionRef.current
        aiPresenceDepartureTimeoutRef.current = window.setTimeout(() => {
            aiPresenceDepartureTimeoutRef.current = null
            if (
                scheduledActivityVersion !== aiPresenceActivityVersionRef.current ||
                activeInlineAIRequestIdsRef.current.size > 0 ||
                aiPresenceRetainedByPromptRef.current
            ) {
                return
            }

            setAICaretFading(true)
            aiPresenceFadeTimeoutRef.current = window.setTimeout(() => {
                aiPresenceFadeTimeoutRef.current = null
                finishAIPresenceDeparture(scheduledActivityVersion)
            }, NOTEBOOK_AI_PRESENCE_FADE_OUT_MS)
        }, NOTEBOOK_AI_PRESENCE_DEPARTURE_IDLE_MS)
    }, [clearAIPresenceTimeouts, finishAIPresenceDeparture])

    const markAIPresenceActive = useCallback(
        (chatId: string): void => {
            activeInlineAIRequestIdsRef.current.add(chatId)
            aiPresenceActivityVersionRef.current += 1
            clearAIPresenceTimeouts()
            setAICaretFading(false)
            setMarkdownAIPresenceActive(true)
        },
        [clearAIPresenceTimeouts, setMarkdownAIPresenceActive]
    )

    const retainAIPresenceForPrompt = useCallback((): void => {
        const promptCaretPosition = getNotebookAIPromptCaretPosition(markdownEditorValueRef.current)
        if (!promptCaretPosition) {
            return
        }

        if (!aiPresenceRetainedByPromptRef.current) {
            aiPresenceActivityVersionRef.current += 1
        }
        aiPresenceRetainedByPromptRef.current = true
        clearAIPresenceTimeouts()
        setAICaretFading(false)
        setAICaretPosition(promptCaretPosition)
        setMarkdownAIPresenceActive(true)
    }, [clearAIPresenceTimeouts, setMarkdownAIPresenceActive])

    const markAIPresenceInactive = useCallback(
        (chatId: string): void => {
            activeInlineAIRequestIdsRef.current.delete(chatId)
            scheduleAIPresenceDeparture()
        },
        [scheduleAIPresenceDeparture]
    )

    useEffect(() => clearAIPresenceTimeouts, [clearAIPresenceTimeouts])

    useEffect(
        () => () => {
            aiPresenceRetainedByPromptRef.current = false
            setMarkdownAIPresenceActive(false)
        },
        [setMarkdownAIPresenceActive]
    )

    useEffect(() => {
        const promptCaretPosition = getNotebookAIPromptCaretPosition(markdownEditorValue)
        if (promptCaretPosition) {
            if (!aiPresenceRetainedByPromptRef.current) {
                aiPresenceActivityVersionRef.current += 1
            }
            aiPresenceRetainedByPromptRef.current = true
            clearAIPresenceTimeouts()
            setAICaretFading(false)
            setAICaretPosition(promptCaretPosition)
            setMarkdownAIPresenceActive(true)
            return
        }

        if (!aiPresenceRetainedByPromptRef.current) {
            return
        }

        aiPresenceRetainedByPromptRef.current = false
        scheduleAIPresenceDeparture()
    }, [clearAIPresenceTimeouts, markdownEditorValue, scheduleAIPresenceDeparture, setMarkdownAIPresenceActive])

    const aiCarets = useMemo<RemoteNotebookCaret[]>(
        () =>
            aiCaretPosition
                ? [
                      {
                          clientId: NOTEBOOK_AI_PRESENCE_CLIENT_ID,
                          userName: NOTEBOOK_AI_PRESENCE_NAME,
                          color: NOTEBOOK_AI_PRESENCE_COLOR,
                          position: aiCaretPosition,
                          version: notebook?.version,
                          isFading: aiCaretFading,
                      },
                  ]
                : [],
        [aiCaretFading, aiCaretPosition, notebook?.version]
    )
    const remoteCarets = useMemo<RemoteNotebookCaret[]>(
        () => [...markdownRemoteCarets, ...aiCarets],
        [aiCarets, markdownRemoteCarets]
    )

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
            markAIPresenceActive(chatId)
            setAICaretPosition(getNotebookAICaretPosition(markdownWithResponse, responseNodeIndex))
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
        [markAIPresenceActive, notebook?.short_id, notebook?.title]
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
                if (mode === 'replace') {
                    markdownEditorValueRef.current = artifactMarkdown
                    applyNotebookArtifactMarkdown(content, chatId, mode)
                    inlineAIResponseNodeCountsRef.current[inlineAIRequest.chatId] = 1
                    const responseNodeIndex = Math.max(0, getMarkdownBlockCount(artifactMarkdown) - 1)
                    inlineAIResponseNodeIndicesRef.current[inlineAIRequest.chatId] = responseNodeIndex
                    setAICaretPosition(getNotebookAICaretPosition(artifactMarkdown, responseNodeIndex))
                    return
                }

                const replacedNodeCount = inlineAIResponseNodeCountsRef.current[inlineAIRequest.chatId] ?? 1
                updateMarkdownEditorValue((currentMarkdown) => {
                    const result = replaceNotebookAIResponseMarkdown(
                        currentMarkdown,
                        getInlineAIResponseNodeIndex(inlineAIRequest, inlineAIResponseNodeIndicesRef.current),
                        artifactMarkdown,
                        replacedNodeCount
                    )
                    inlineAIResponseNodeIndicesRef.current[inlineAIRequest.chatId] = result.responseNodeIndex
                    setAICaretPosition(getNotebookAICaretPosition(result.markdown, result.responseNodeIndex))
                    return result.markdown
                })
                inlineAIResponseNodeCountsRef.current[inlineAIRequest.chatId] = getMarkdownBlockCount(artifactMarkdown)
                return
            }

            applyNotebookArtifactMarkdown(content, chatId, mode)
        },
        [applyNotebookArtifactMarkdown, getInlineAIRequest, updateMarkdownEditorValue]
    )

    const [savedInsightPickerTargetNodeId, setSavedInsightPickerTargetNodeId] = useState<string | null>(null)
    // Insert API + target node captured when "Saved insight" is picked, so the modal's async selection
    // can insert into the right node once an insight is chosen.
    const savedInsightInsertRef = useRef<{ api: MarkdownNotebookInsertMenuApi; targetNodeId: string } | null>(null)

    const buildSavedInsightInsertCommands = useCallback(
        (api: MarkdownNotebookInsertMenuApi): InsertCommand[] => [
            {
                key: 'query-saved-insight',
                label: 'Saved insight',
                category: 'Insight',
                icon: <IconGraph />,
                run: (targetNodeId) => {
                    savedInsightInsertRef.current = { api, targetNodeId }
                    setSavedInsightPickerTargetNodeId(targetNodeId)
                },
            },
        ],
        []
    )

    const closeSavedInsightPicker = useCallback((): void => {
        savedInsightInsertRef.current = null
        setSavedInsightPickerTargetNodeId(null)
    }, [])

    const handleSavedInsightPicked = useCallback((shortId: string, title: string): void => {
        const pending = savedInsightInsertRef.current
        if (pending) {
            pending.api.insertComponent(pending.targetNodeId, 'Query', {
                query: { kind: 'SavedInsightNode', shortId },
                // The insight is already configured via the picker, so render results-only — hiding the
                // settings panel (the "Edit the insight" / "Detach from insight" controls) by default.
                hideFilters: true,
                // Label the node with the insight's name so the toolbar shows it instead of the short id.
                ...(title ? { title } : {}),
            })
        }
        savedInsightInsertRef.current = null
        setSavedInsightPickerTargetNodeId(null)
    }, [])

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
                setAICaretPosition(getNotebookAICaretPosition(result.markdown, result.responseNodeIndex))
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
                    setAICaretPosition(getNotebookAICaretPosition(result.markdown, result.responseNodeIndex))
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
            retainAIPresenceForPrompt()
            setFocusAIPromptRequest((currentRequest) => (currentRequest ?? 0) + 1)

            window.setTimeout(() => {
                delete inlineAIResponseNodeCountsRef.current[request.chatId]
                delete inlineAIResponseNodeIndicesRef.current[request.chatId]
                markAIPresenceInactive(request.chatId)
                setInlineAIRequests((currentRequests) =>
                    currentRequests.filter((currentRequest) => currentRequest.chatId !== request.chatId)
                )
            }, 0)
        },
        [markAIPresenceInactive, retainAIPresenceForPrompt, updateMarkdownEditorValue]
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
                setAICaretPosition(getNotebookAICaretPosition(result.markdown, result.responseNodeIndex))
                return result.markdown
            })

            delete inlineAIResponseNodeCountsRef.current[request.chatId]
            delete inlineAIResponseNodeIndicesRef.current[request.chatId]
            markAIPresenceInactive(request.chatId)
            setInlineAIRequests((currentRequests) =>
                currentRequests.filter((currentRequest) => currentRequest.chatId !== request.chatId)
            )
        },
        [markAIPresenceInactive, updateMarkdownEditorValue]
    )

    return (
        <MarkdownNotebookRuntimeContext.Provider value={runtimeContext}>
            <MarkdownNotebook
                value={markdownEditorValue}
                remoteValue={remoteMarkdown}
                remoteVersion={notebook?.version}
                mode={isEditable ? 'edit' : 'view'}
                registry={NOTEBOOK_MARKDOWN_REGISTRY}
                extraInsertCommands={isEditable ? buildSavedInsightInsertCommands : undefined}
                onChange={isEditable ? handleMarkdownEditorChange : undefined}
                onConflict={reportMarkdownMergeConflicts}
                remoteCarets={remoteCarets}
                onCaretChange={isEditable ? publishMarkdownCaret : undefined}
                onAskAI={isEditable ? handleAskAI : undefined}
                isAskAIDisabled={inlineAIRequests.length > 0}
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
            {isEditable && (
                <MarkdownNotebookSavedInsightPicker
                    isOpen={savedInsightPickerTargetNodeId !== null}
                    onClose={closeSavedInsightPicker}
                    onSelect={handleSavedInsightPicked}
                />
            )}
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

export function getNotebookAICaretPosition(
    markdown: string,
    responseNodeIndex: number
): MarkdownNotebookCaretPosition | null {
    const nodes = parseMarkdownNotebook(markdown).nodes
    if (!nodes.length) {
        return null
    }

    const nodeIndex = Math.max(0, Math.min(responseNodeIndex, nodes.length - 1))
    return getNotebookNodeEndCaretPosition(nodes[nodeIndex], nodeIndex)
}

export function getNotebookAIPromptCaretPosition(markdown: string): MarkdownNotebookCaretPosition | null {
    const nodes = parseMarkdownNotebook(markdown).nodes
    for (let promptNodeIndex = nodes.length - 1; promptNodeIndex >= 0; promptNodeIndex--) {
        if (!isNotebookAIPromptNode(nodes[promptNodeIndex])) {
            continue
        }

        for (let nodeIndex = promptNodeIndex - 1; nodeIndex >= 0; nodeIndex--) {
            if (!isNotebookAIPromptNode(nodes[nodeIndex])) {
                return getNotebookNodeEndCaretPosition(nodes[nodeIndex], nodeIndex)
            }
        }
    }

    return null
}

function isNotebookAIPromptNode(node: NotebookBlockNode): boolean {
    return node.type === 'component' && node.tagName === 'Prompt'
}

function getNotebookNodeEndCaretPosition(node: NotebookBlockNode, nodeIndex: number): MarkdownNotebookCaretPosition {
    if (node.type === 'paragraph' || node.type === 'heading' || node.type === 'blockquote') {
        return { nodeIndex, offset: getInlineText(node.children).length }
    }
    if (node.type === 'code') {
        return { nodeIndex, offset: node.text.length }
    }
    if (node.type === 'list' && node.items.length > 0) {
        const listItemIndex = node.items.length - 1
        return {
            nodeIndex,
            listItemIndex,
            offset: getInlineText(node.items[listItemIndex].children).length,
        }
    }
    return { nodeIndex }
}
