import { useActions, useMountedLogic, useValues } from 'kea'
import { useContext, useEffect, useMemo, useRef } from 'react'

import { maxLogic } from 'scenes/max/maxLogic'
import type { maxLogicType } from 'scenes/max/maxLogicType'
import { MaxThreadLogicProps, ThreadMessage, maxThreadLogic } from 'scenes/max/maxThreadLogic'
import type { MaxUIContext } from 'scenes/max/maxTypes'

import { ArtifactContentType, AssistantMessageType } from '~/queries/schema/schema-assistant-messages'

import {
    InlineNotebookAIRequest,
    MarkdownNotebookRuntimeContext,
    NotebookApplicableArtifactThreadMessage,
    NotebookArtifactApplyRequest,
} from './markdownNotebookRuntime'
import { visualizationArtifactContentToNotebookArtifactContent } from './markdownNotebookV2'

export function InlineNotebookAIRunner({
    request,
    onComplete,
    onError,
    onAssistantMessage,
}: {
    request: InlineNotebookAIRequest
    onComplete: (request: InlineNotebookAIRequest, completion: InlineAICompletion) => void
    onError: (request: InlineNotebookAIRequest, completion: InlineAICompletion) => void
    onAssistantMessage?: (request: InlineNotebookAIRequest, message: InlineAIAssistantMessage) => void
}): JSX.Element {
    const maxLogicProps = useMemo<maxLogicType['props']>(
        () => ({ panelId: request.panelId, initialFrontendConversationId: request.conversationId, syncUrl: false }),
        [request.conversationId, request.panelId]
    )
    const maxLogicInstance = maxLogic(maxLogicProps)
    useMountedLogic(maxLogicInstance)

    const { askMax } = useActions(maxLogicInstance)
    const { threadLogicProps } = useValues(maxLogicInstance)

    if (threadLogicProps.conversationId !== request.conversationId) {
        return <></>
    }

    return (
        <InlineNotebookAIThread
            request={request}
            threadLogicProps={threadLogicProps}
            askMax={askMax}
            onComplete={onComplete}
            onError={onError}
            onAssistantMessage={onAssistantMessage}
        />
    )
}

export function InlineNotebookAIThread({
    request,
    threadLogicProps,
    askMax,
    onComplete,
    onError,
    onAssistantMessage,
}: {
    request: InlineNotebookAIRequest
    threadLogicProps: MaxThreadLogicProps
    askMax: (prompt: string | null, addToThread?: boolean, uiContext?: Partial<MaxUIContext>) => void
    onComplete: (request: InlineNotebookAIRequest, completion: InlineAICompletion) => void
    onError: (request: InlineNotebookAIRequest, completion: InlineAICompletion) => void
    onAssistantMessage?: (request: InlineNotebookAIRequest, message: InlineAIAssistantMessage) => void
}): null {
    const threadLogicInstance = maxThreadLogic(threadLogicProps)
    useMountedLogic(threadLogicInstance)

    const { threadRaw, threadLoading } = useValues(threadLogicInstance)
    const didAskRef = useRef(false)
    const didCompleteRef = useRef(false)
    const reportedAssistantMessagesRef = useRef<Map<string, string>>(new Map())
    useApplyNotebookArtifactMessages(threadRaw, request.conversationId)

    useEffect(() => {
        if (didAskRef.current) {
            return
        }

        didAskRef.current = true
        askMax(request.query, true, request.uiContext)
    }, [askMax, request])

    useEffect(() => {
        if (!onAssistantMessage) {
            return
        }

        const hasArtifact = hasCompletedNotebookArtifactMessage(threadRaw)

        threadRaw.forEach((message, index) => {
            if (message.type !== AssistantMessageType.Assistant) {
                return
            }

            const content = getMessageContent(message).trim()
            if (!content) {
                return
            }

            const id = getThreadMessageId(message, index)
            if (reportedAssistantMessagesRef.current.get(id) === content) {
                return
            }

            reportedAssistantMessagesRef.current.set(id, content)
            onAssistantMessage(request, { id, content, hasArtifact })
        })
    }, [onAssistantMessage, request, threadRaw])

    useEffect(() => {
        if (!didAskRef.current || didCompleteRef.current || threadLoading) {
            return
        }

        const completion = getInlineAICompletion(threadRaw)
        if (!completion) {
            return
        }

        didCompleteRef.current = true
        if (completion.status === 'error') {
            onError(request, completion)
            return
        }

        onComplete(request, completion)
    }, [onComplete, onError, request, threadLoading, threadRaw])

    return null
}

export type InlineAICompletion = {
    status: 'done' | 'error'
    message: string
    kind: 'assistant' | 'artifact' | 'error' | 'generic'
    hasArtifact: boolean
}

export type InlineAIAssistantMessage = {
    id: string
    content: string
    hasArtifact: boolean
}

export function getInlineAICompletion(threadRaw: ThreadMessage[]): InlineAICompletion | null {
    const hasArtifact = hasCompletedNotebookArtifactMessage(threadRaw)
    const lastErrorMessage = [...threadRaw]
        .reverse()
        .find((message) => message.type === AssistantMessageType.Failure || message.status === 'error')
    if (lastErrorMessage) {
        return {
            status: 'error',
            kind: 'error',
            hasArtifact,
            message: getInlineAIStatusText(
                'content' in lastErrorMessage && typeof lastErrorMessage.content === 'string'
                    ? lastErrorMessage.content
                    : undefined,
                'PostHog AI could not finish this request.'
            ),
        }
    }

    const completedMessages = threadRaw.filter((message) => message.status === 'completed')
    // Assistant messages without content (e.g. thinking-only traces) cannot describe the outcome.
    const lastAssistantMessage = [...completedMessages]
        .reverse()
        .find(
            (message) =>
                message.type !== AssistantMessageType.Human &&
                (message.type !== AssistantMessageType.Assistant || !!getMessageContent(message).trim())
        )
    if (!lastAssistantMessage) {
        return null
    }

    if (lastAssistantMessage.type === AssistantMessageType.Assistant) {
        return {
            status: 'done',
            kind: 'assistant',
            hasArtifact,
            message: getInlineAIStatusText(lastAssistantMessage.content, 'PostHog AI finished.'),
        }
    }

    if (
        lastAssistantMessage.type === AssistantMessageType.Notebook ||
        isCompletedNotebookApplicableArtifactMessage(lastAssistantMessage)
    ) {
        return {
            status: 'done',
            kind: 'artifact',
            hasArtifact,
            message: 'Updated the notebook.',
        }
    }

    return {
        status: 'done',
        kind: 'generic',
        hasArtifact,
        message: 'PostHog AI finished.',
    }
}

function hasCompletedNotebookArtifactMessage(threadRaw: ThreadMessage[]): boolean {
    return threadRaw.some(
        (message) =>
            message.status === 'completed' &&
            (message.type === AssistantMessageType.Notebook || isCompletedNotebookApplicableArtifactMessage(message))
    )
}

export function getInlineAIStatusText(value: string | undefined, fallback: string): string {
    const oneLineValue = value?.replace(/\s+/g, ' ').trim()
    if (!oneLineValue) {
        return fallback
    }
    return oneLineValue.length > 160 ? `${oneLineValue.slice(0, 157)}...` : oneLineValue
}

export function useApplyNotebookArtifactMessages(threadRaw: ThreadMessage[], conversationId: string): void {
    const runtimeContext = useContext(MarkdownNotebookRuntimeContext)
    const appliedArtifactKeysRef = useRef<Set<string>>(new Set())

    useEffect(() => {
        if (!runtimeContext) {
            return
        }

        for (const message of threadRaw) {
            if (!isCompletedNotebookApplicableArtifactMessage(message)) {
                continue
            }

            const artifactRequest = getNotebookArtifactApplyRequestForMessage(message)
            const artifactKey = getNotebookArtifactMessageKey(message)
            if (appliedArtifactKeysRef.current.has(artifactKey)) {
                continue
            }

            runtimeContext.applyNotebookArtifactContent(artifactRequest.content, conversationId, artifactRequest.mode)
            appliedArtifactKeysRef.current.add(artifactKey)
        }
    }, [conversationId, runtimeContext, threadRaw])
}

export function getNotebookArtifactApplyRequestForMessage(
    message: NotebookApplicableArtifactThreadMessage
): NotebookArtifactApplyRequest {
    if (message.content.content_type === ArtifactContentType.Notebook) {
        return { content: message.content, mode: 'replace' }
    }

    return {
        content: visualizationArtifactContentToNotebookArtifactContent(message.content),
        mode: 'insert-after-response',
    }
}

export function isCompletedNotebookApplicableArtifactMessage(
    message: ThreadMessage
): message is NotebookApplicableArtifactThreadMessage {
    return (
        message.type === AssistantMessageType.Artifact &&
        message.status === 'completed' &&
        (message.content.content_type === ArtifactContentType.Notebook ||
            message.content.content_type === ArtifactContentType.Visualization)
    )
}

export function getNotebookArtifactMessageKey(message: NotebookApplicableArtifactThreadMessage): string {
    return `${message.artifact_id}:${message.id ?? ''}:${JSON.stringify(message.content)}`
}

export function getThreadMessageId(message: ThreadMessage, index: number): string {
    return 'id' in message && typeof message.id === 'string' ? message.id : `notebook-ai-message-${index}`
}

export function getMessageContent(message: ThreadMessage): string {
    return 'content' in message && typeof message.content === 'string' ? message.content : ''
}
