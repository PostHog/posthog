import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconFlask, IconGraph } from '@posthog/icons'

import { MarkdownNotebook, parseMarkdownNotebook } from 'lib/components/MarkdownNotebook'
import type {
    InsertCommand,
    MarkdownNotebookAskAIRequest,
    MarkdownNotebookInsertMenuApi,
} from 'lib/components/MarkdownNotebook'
import {
    insertNotebookAIFollowUpPromptAfterResponse,
    rebaseNotebookAIResponseRange,
    replaceNotebookAIResponseMarkdown,
    streamNotebookAIResponseMarkdown,
} from 'lib/components/MarkdownNotebook/notebookAI'
import type { MarkdownNotebookCaretPosition, RemoteNotebookCaret } from 'lib/components/MarkdownNotebook/remoteCarets'
import type { NotebookBlockNode } from 'lib/components/MarkdownNotebook/types'
import { getInlineText } from 'lib/components/MarkdownNotebook/utils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { uuid } from 'lib/utils/dom'

import type { NotebookArtifactContent } from '~/queries/schema/schema-assistant-messages'

import { MarkdownNotebookExperimentPicker } from './MarkdownNotebookExperimentPicker'
import { InlineAIAssistantMessage, InlineAICompletion, InlineNotebookAIRunner } from './MarkdownNotebookInlineAI'
import { getMarkdownRegistryForFeatureFlags } from './markdownNotebookRegistry'
import {
    InlineNotebookAIRequest,
    MarkdownNotebookRuntimeContext,
    MarkdownNotebookRuntimeContextValue,
    NotebookArtifactApplyMode,
    getInlineNotebookAIPanelId,
    getInlineNotebookAIUIContext,
} from './markdownNotebookRuntime'
import { MarkdownNotebookSavedInsightPicker } from './MarkdownNotebookSavedInsightPicker'
import { getMarkdownNotebookMarkdown, notebookArtifactContentToMarkdown } from './markdownNotebookV2'
import { notebookLogic } from './notebookLogic'
import {
    NOTEBOOK_AI_PRESENCE_COLOR,
    NOTEBOOK_AI_PRESENCE_CLIENT_ID,
    NOTEBOOK_AI_PRESENCE_NAME,
} from './notebookPresence'
import { notebookSettingsLogic } from './notebookSettingsLogic'

const NOTEBOOK_AI_FOLLOW_UP_PROMPT_MARKDOWN = '<Prompt question="" />'
const NOTEBOOK_AI_PRESENCE_DEPARTURE_IDLE_MS = 5_000
const NOTEBOOK_AI_PRESENCE_FADE_OUT_MS = 300

type MarkdownNotebookV2Props = {
    debugOpen?: boolean
    onDebugOpenChange?: (isOpen: boolean) => void
}

export function MarkdownNotebookV2({ debugOpen, onDebugOpenChange }: MarkdownNotebookV2Props): JSX.Element {
    const { isEditable, notebook, markdownEditorValue, markdownEditorInteractionActive, markdownRemoteCarets } =
        useValues(notebookLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const markdownRegistry = useMemo(() => getMarkdownRegistryForFeatureFlags(featureFlags), [featureFlags])
    const {
        handleMarkdownEditorChange,
        setMarkdownEditorInteractionActive,
        applyNotebookArtifactMarkdown,
        reportMarkdownMergeConflicts,
        publishMarkdownCaret,
        setMarkdownAIPresenceActive,
    } = useActions(notebookLogic)
    const { setShowKernelInfo } = useActions(notebookSettingsLogic)
    const remoteMarkdown = getMarkdownNotebookMarkdown(notebook?.content)
    const [inlineAIRequests, setInlineAIRequests] = useState<InlineNotebookAIRequest[]>([])
    const [aiCaretPosition, setAICaretPosition] = useState<MarkdownNotebookCaretPosition | null>(null)
    const [aiCaretFading, setAICaretFading] = useState(false)
    const [aiCaretThinking, setAICaretThinking] = useState(false)
    const markdownEditorValueRef = useRef(markdownEditorValue)
    const inlineAIResponseNodeCountsRef = useRef<Record<string, number>>({})
    const inlineAIResponseNodeIndicesRef = useRef<Record<string, number>>({})
    const activeInlineAIRequestIdsRef = useRef<Set<string>>(new Set())
    const aiPresenceRetainedByPromptRef = useRef(false)
    const aiPresenceActivityVersionRef = useRef(0)
    const aiPresenceDepartureTimeoutRef = useRef<number | null>(null)
    const aiPresenceFadeTimeoutRef = useRef<number | null>(null)
    const [focusAIPromptRequest, setFocusAIPromptRequest] = useState<number | undefined>(undefined)
    const [internalDebugOpen, setInternalDebugOpen] = useState(false)
    const isDebugOpen = debugOpen ?? internalDebugOpen

    useEffect(() => {
        markdownEditorValueRef.current = markdownEditorValue
    }, [markdownEditorValue])

    const setMarkdownSourceOpen = useCallback(
        (isOpen: boolean): void => {
            if (debugOpen === undefined) {
                setInternalDebugOpen(isOpen)
            }
            onDebugOpenChange?.(isOpen)
        },
        [debugOpen, onDebugOpenChange]
    )

    const handleDebugOpenChange = useCallback(
        (isOpen: boolean): void => {
            if (isOpen) {
                setShowKernelInfo(false)
            }
            setMarkdownSourceOpen(isOpen)
        },
        [setMarkdownSourceOpen, setShowKernelInfo]
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

    const handleMarkdownNotebookChange = useCallback(
        (markdown: string): void => {
            const previousMarkdown = markdownEditorValueRef.current
            for (const request of inlineAIRequests) {
                const currentRange = rebaseNotebookAIResponseRange(
                    previousMarkdown,
                    markdown,
                    getInlineAIResponseNodeIndex(request, inlineAIResponseNodeIndicesRef.current),
                    inlineAIResponseNodeCountsRef.current[request.conversationId] ?? 1
                )
                inlineAIResponseNodeIndicesRef.current[request.conversationId] = currentRange.responseNodeIndex
                inlineAIResponseNodeCountsRef.current[request.conversationId] = currentRange.responseNodeCount
            }
            markdownEditorValueRef.current = markdown
            handleMarkdownEditorChange(markdown)
        },
        [handleMarkdownEditorChange, inlineAIRequests]
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
            setAICaretThinking(false)
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
        (conversationId: string): void => {
            activeInlineAIRequestIdsRef.current.add(conversationId)
            aiPresenceActivityVersionRef.current += 1
            clearAIPresenceTimeouts()
            setAICaretFading(false)
            setAICaretThinking(true)
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
        setAICaretThinking(false)
        setAICaretPosition(promptCaretPosition)
        setMarkdownAIPresenceActive(true)
    }, [clearAIPresenceTimeouts, setMarkdownAIPresenceActive])

    const markAIPresenceInactive = useCallback(
        (conversationId: string): void => {
            activeInlineAIRequestIdsRef.current.delete(conversationId)
            if (activeInlineAIRequestIdsRef.current.size === 0) {
                setAICaretThinking(false)
            }
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
            setAICaretThinking(false)
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
                          isAI: true,
                          isAIThinking: aiCaretThinking,
                          isFading: aiCaretFading,
                      },
                  ]
                : [],
        [aiCaretFading, aiCaretPosition, aiCaretThinking, notebook?.version]
    )
    const remoteCarets = useMemo<RemoteNotebookCaret[]>(
        () => [...markdownRemoteCarets, ...aiCarets],
        [aiCarets, markdownRemoteCarets]
    )

    const handleAskAI = useCallback(
        ({
            conversationId,
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
            markAIPresenceActive(conversationId)
            setAICaretPosition(getNotebookAICaretPosition(markdownWithResponse, responseNodeIndex))
            const uiContext = getInlineNotebookAIUIContext({
                notebookShortId: notebook?.short_id ?? null,
                notebookTitle: notebook?.title ?? 'Untitled notebook',
                markdown: markdownWithResponse,
                conversationId,
                responseMarker: responseMarker,
            })

            const inlineAIRequest: InlineNotebookAIRequest = {
                conversationId,
                panelId: getInlineNotebookAIPanelId(conversationId, 'inline'),
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
                ...currentRequests.filter((currentRequest) => currentRequest.conversationId !== conversationId),
                inlineAIRequest,
            ])
            inlineAIResponseNodeCountsRef.current[conversationId] = 1
            inlineAIResponseNodeIndicesRef.current[conversationId] = responseNodeIndex
        },
        [markAIPresenceActive, notebook?.short_id, notebook?.title]
    )

    const getInlineAIRequest = useCallback(
        (conversationId: string | undefined): InlineNotebookAIRequest | null => {
            if (!conversationId) {
                return null
            }
            return inlineAIRequests.find((request) => request.conversationId === conversationId) ?? null
        },
        [inlineAIRequests]
    )

    const applyNotebookArtifactContent = useCallback(
        (
            content: NotebookArtifactContent,
            conversationId?: string,
            mode: NotebookArtifactApplyMode = 'replace'
        ): void => {
            const inlineAIRequest = getInlineAIRequest(conversationId)
            if (inlineAIRequest) {
                const artifactMarkdown = notebookArtifactContentToMarkdown(content)
                if (mode === 'replace') {
                    markdownEditorValueRef.current = artifactMarkdown
                    applyNotebookArtifactMarkdown(content, conversationId, mode)
                    inlineAIResponseNodeCountsRef.current[inlineAIRequest.conversationId] = 1
                    const responseNodeIndex = Math.max(0, getMarkdownBlockCount(artifactMarkdown) - 1)
                    inlineAIResponseNodeIndicesRef.current[inlineAIRequest.conversationId] = responseNodeIndex
                    setAICaretPosition(getNotebookAICaretPosition(artifactMarkdown, responseNodeIndex))
                    return
                }

                const replacedNodeCount = inlineAIResponseNodeCountsRef.current[inlineAIRequest.conversationId] ?? 1
                updateMarkdownEditorValue((currentMarkdown) => {
                    const result = replaceNotebookAIResponseMarkdown(
                        currentMarkdown,
                        getInlineAIResponseNodeIndex(inlineAIRequest, inlineAIResponseNodeIndicesRef.current),
                        artifactMarkdown,
                        replacedNodeCount
                    )
                    inlineAIResponseNodeIndicesRef.current[inlineAIRequest.conversationId] = result.responseNodeIndex
                    setAICaretPosition(getNotebookAICaretPosition(result.markdown, result.responseNodeIndex))
                    return result.markdown
                })
                inlineAIResponseNodeCountsRef.current[inlineAIRequest.conversationId] =
                    getMarkdownBlockCount(artifactMarkdown)
                return
            }

            applyNotebookArtifactMarkdown(content, conversationId, mode)
        },
        [applyNotebookArtifactMarkdown, getInlineAIRequest, updateMarkdownEditorValue]
    )

    const [savedInsightPickerTargetNodeId, setSavedInsightPickerTargetNodeId] = useState<string | null>(null)
    const [experimentPickerTargetNodeId, setExperimentPickerTargetNodeId] = useState<string | null>(null)
    // Insert API + target node captured when "Saved insight" / "Experiment" is picked, so the modal's
    // async selection can insert into the right node once an entity is chosen.
    const savedInsightInsertRef = useRef<{ api: MarkdownNotebookInsertMenuApi; targetNodeId: string } | null>(null)
    const experimentInsertRef = useRef<{ api: MarkdownNotebookInsertMenuApi; targetNodeId: string } | null>(null)

    const buildExtraInsertCommands = useCallback(
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
            {
                key: 'experiment',
                label: 'Experiment',
                category: 'Experiment',
                icon: <IconFlask />,
                run: (targetNodeId) => {
                    experimentInsertRef.current = { api, targetNodeId }
                    setExperimentPickerTargetNodeId(targetNodeId)
                },
            },
        ],
        []
    )

    const closeSavedInsightPicker = useCallback((): void => {
        savedInsightInsertRef.current = null
        setSavedInsightPickerTargetNodeId(null)
    }, [])

    const closeExperimentPicker = useCallback((): void => {
        experimentInsertRef.current = null
        setExperimentPickerTargetNodeId(null)
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

    const handleExperimentPicked = useCallback((experimentId: number): void => {
        const pending = experimentInsertRef.current
        if (pending) {
            pending.api.insertComponent(pending.targetNodeId, 'Experiment', { id: experimentId })
        }
        experimentInsertRef.current = null
        setExperimentPickerTargetNodeId(null)
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

            const replacedNodeCount = inlineAIResponseNodeCountsRef.current[request.conversationId] ?? 1
            updateMarkdownEditorValue((currentMarkdown) => {
                const result = streamNotebookAIResponseMarkdown(
                    currentMarkdown,
                    getInlineAIResponseNodeIndex(request, inlineAIResponseNodeIndicesRef.current),
                    message.content,
                    replacedNodeCount
                )
                inlineAIResponseNodeIndicesRef.current[request.conversationId] = result.responseNodeIndex
                inlineAIResponseNodeCountsRef.current[request.conversationId] = result.responseNodeCount
                setAICaretPosition(getNotebookAICaretPosition(result.markdown, result.responseNodeIndex))
                return result.markdown
            })
        },
        [updateMarkdownEditorValue]
    )

    const handleInlineAIComplete = useCallback(
        (request: InlineNotebookAIRequest, completion: InlineAICompletion): void => {
            if (completion.kind !== 'assistant' && completion.kind !== 'artifact' && !completion.hasArtifact) {
                const replacedNodeCount = inlineAIResponseNodeCountsRef.current[request.conversationId] ?? 1
                updateMarkdownEditorValue((currentMarkdown) => {
                    const result = replaceNotebookAIResponseMarkdown(
                        currentMarkdown,
                        getInlineAIResponseNodeIndex(request, inlineAIResponseNodeIndicesRef.current),
                        completion.message,
                        replacedNodeCount
                    )
                    inlineAIResponseNodeIndicesRef.current[request.conversationId] = result.responseNodeIndex
                    setAICaretPosition(getNotebookAICaretPosition(result.markdown, result.responseNodeIndex))
                    return result.markdown
                })
                inlineAIResponseNodeCountsRef.current[request.conversationId] = getMarkdownBlockCount(
                    completion.message
                )
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
                delete inlineAIResponseNodeCountsRef.current[request.conversationId]
                delete inlineAIResponseNodeIndicesRef.current[request.conversationId]
                markAIPresenceInactive(request.conversationId)
                setInlineAIRequests((currentRequests) =>
                    currentRequests.filter((currentRequest) => currentRequest.conversationId !== request.conversationId)
                )
            }, 0)
        },
        [markAIPresenceInactive, retainAIPresenceForPrompt, updateMarkdownEditorValue]
    )

    const handleInlineAIError = useCallback(
        (request: InlineNotebookAIRequest, completion: InlineAICompletion): void => {
            const replacedNodeCount = inlineAIResponseNodeCountsRef.current[request.conversationId] ?? 1
            updateMarkdownEditorValue((currentMarkdown) => {
                const result = replaceNotebookAIResponseMarkdown(
                    currentMarkdown,
                    getInlineAIResponseNodeIndex(request, inlineAIResponseNodeIndicesRef.current),
                    completion.message,
                    replacedNodeCount
                )
                inlineAIResponseNodeIndicesRef.current[request.conversationId] = result.responseNodeIndex
                setAICaretPosition(getNotebookAICaretPosition(result.markdown, result.responseNodeIndex))
                return result.markdown
            })

            delete inlineAIResponseNodeCountsRef.current[request.conversationId]
            delete inlineAIResponseNodeIndicesRef.current[request.conversationId]
            markAIPresenceInactive(request.conversationId)
            setInlineAIRequests((currentRequests) =>
                currentRequests.filter((currentRequest) => currentRequest.conversationId !== request.conversationId)
            )
        },
        [markAIPresenceInactive, updateMarkdownEditorValue]
    )

    const aiWritingNodeIndexes = useMemo(
        () =>
            inlineAIRequests.map((request) =>
                getInlineAIResponseNodeIndex(request, inlineAIResponseNodeIndicesRef.current)
            ),
        [inlineAIRequests, markdownEditorValue]
    )

    return (
        <MarkdownNotebookRuntimeContext.Provider value={runtimeContext}>
            <MarkdownNotebook
                value={markdownEditorValue}
                remoteValue={remoteMarkdown}
                remoteVersion={notebook?.version}
                mode={isEditable ? 'edit' : 'view'}
                registry={markdownRegistry}
                extraInsertCommands={isEditable ? buildExtraInsertCommands : undefined}
                onChange={isEditable ? handleMarkdownNotebookChange : undefined}
                onConflict={reportMarkdownMergeConflicts}
                remoteCarets={remoteCarets}
                onCaretChange={isEditable ? publishMarkdownCaret : undefined}
                onAskAI={isEditable ? handleAskAI : undefined}
                isAskAIDisabled={inlineAIRequests.length > 0}
                createAIConversationId={uuid}
                deferRemoteValue={markdownEditorInteractionActive}
                onInteractionStateChange={setMarkdownEditorInteractionActive}
                className="Notebook__markdown-v2"
                data-attr="notebook-markdown-v2"
                autoFocus={isEditable}
                showDebug={isEditable}
                debugOpen={isDebugOpen}
                onDebugOpenChange={handleDebugOpenChange}
                focusAIPromptRequest={focusAIPromptRequest}
                aiWritingNodeIndexes={aiWritingNodeIndexes}
            />
            {inlineAIRequests.map((request) => (
                <InlineNotebookAIRunner
                    key={request.conversationId}
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
            {isEditable && (
                <MarkdownNotebookExperimentPicker
                    isOpen={experimentPickerTargetNodeId !== null}
                    onClose={closeExperimentPicker}
                    onSelect={handleExperimentPicked}
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
    return responseNodeIndices[request.conversationId] ?? request.responseNodeIndex
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
