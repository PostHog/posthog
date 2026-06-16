import { useActions, useMountedLogic, useValues } from 'kea'
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'

import { IconMessage, IconSend, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import {
    NotebookComponentBlockNode,
    NotebookComponentProps,
    NotebookComponentRenderProps,
} from 'lib/components/MarkdownNotebook/types'
import { MarkdownMessage } from 'scenes/max/MarkdownMessage'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { maxLogic } from 'scenes/max/maxLogic'
import type { maxLogicType } from 'scenes/max/maxLogicType'
import { MaxThreadLogicProps, ThreadMessage, maxThreadLogic } from 'scenes/max/maxThreadLogic'
import type { MaxUIContext } from 'scenes/max/maxTypes'

import { ArtifactContentType, AssistantMessageType } from '~/queries/schema/schema-assistant-messages'

import { getNotebookStringProp, getUnknownStringProp, summarizeTitle } from './markdownNotebookRegistry'
import {
    InlineNotebookAIRequest,
    MarkdownNotebookRuntimeContext,
    NotebookApplicableArtifactThreadMessage,
    NotebookArtifactApplyRequest,
    getInlineNotebookAIPanelId,
    getNotebookAIChatUIContext,
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
        () => ({ panelId: request.panelId, initialFrontendConversationId: request.chatId, syncUrl: false }),
        [request.chatId, request.panelId]
    )
    const maxLogicInstance = maxLogic(maxLogicProps)
    useMountedLogic(maxLogicInstance)

    const { askMax } = useActions(maxLogicInstance)
    const { threadLogicProps } = useValues(maxLogicInstance)

    if (threadLogicProps.conversationId !== request.chatId) {
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
    const reportedAssistantMessageIdsRef = useRef<Set<string>>(new Set())
    useApplyNotebookArtifactMessages(threadRaw, request.chatId)

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

        threadRaw.forEach((message, index) => {
            if (message.type !== AssistantMessageType.Assistant || message.status !== 'completed') {
                return
            }

            const content = getMessageContent(message).trim()
            if (!content) {
                return
            }

            const id = getThreadMessageId(message, index)
            if (reportedAssistantMessageIdsRef.current.has(id)) {
                return
            }

            reportedAssistantMessageIdsRef.current.add(id)
            onAssistantMessage(request, { id, content })
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
}

export function getInlineAICompletion(threadRaw: ThreadMessage[]): InlineAICompletion | null {
    const hasArtifact = threadRaw.some(
        (message) =>
            message.status === 'completed' &&
            (message.type === AssistantMessageType.Notebook || isCompletedNotebookApplicableArtifactMessage(message))
    )
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

export function getInlineAIStatusText(value: string | undefined, fallback: string): string {
    const oneLineValue = value?.replace(/\s+/g, ' ').trim()
    if (!oneLineValue) {
        return fallback
    }
    return oneLineValue.length > 160 ? `${oneLineValue.slice(0, 157)}...` : oneLineValue
}

export function useApplyNotebookArtifactMessages(threadRaw: ThreadMessage[], chatId: string): void {
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

            runtimeContext.applyNotebookArtifactContent(artifactRequest.content, chatId, artifactRequest.mode)
            appliedArtifactKeysRef.current.add(artifactKey)
        }
    }, [chatId, runtimeContext, threadRaw])
}

export function getNotebookArtifactApplyRequestForMessage(
    message: NotebookApplicableArtifactThreadMessage
): NotebookArtifactApplyRequest {
    if (message.content.content_type === ArtifactContentType.Notebook) {
        return { content: message.content, mode: 'replace' }
    }

    return {
        content: visualizationArtifactContentToNotebookArtifactContent(message.content),
        mode: 'insert-after-chat',
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

export function getNotebookAIChatTitle(node: NotebookComponentBlockNode): string | null {
    return (
        getNotebookStringProp(node.props.title) ??
        summarizeTitle(getNotebookStringProp(node.props.lastAnswer) ?? getNotebookStringProp(node.props.answer))
    )
}

export function NotebookAIChat({ node, updateProps, deleteNode }: NotebookComponentRenderProps): JSX.Element {
    const cachedLastAnswer = getNotebookStringProp(node.props.lastAnswer) ?? getNotebookStringProp(node.props.answer)
    const hasLegacyAnswer = node.props.answer !== undefined
    const chatId = getNotebookStringProp(node.props.id)
    const cachedTitle = getNotebookStringProp(node.props.title)
    const hasPersistedMessages = node.props.messages !== undefined
    const shouldStartActive = !cachedLastAnswer
    const [isThreadActive, setIsThreadActive] = useState(shouldStartActive)
    const [loadOlderMessages, setLoadOlderMessages] = useState(false)
    const [queuedReply, setQueuedReply] = useState<string | null>(null)
    const [activeBaseMessages, setActiveBaseMessages] = useState<NotebookAIChatMessage[]>(() =>
        shouldStartActive ? getNotebookAIChatBaseMessages(cachedLastAnswer) : []
    )

    useEffect(() => {
        if (hasPersistedMessages) {
            updateProps({ messages: undefined })
        }
    }, [hasPersistedMessages, updateProps])

    if (!chatId) {
        return <div className="MarkdownNotebook__component-preview">Missing AI chat id.</div>
    }

    if (cachedLastAnswer && !isThreadActive) {
        const baseMessages = getNotebookAIChatBaseMessages(cachedLastAnswer)

        return (
            <NotebookAIChatConversation
                messages={baseMessages}
                canReply
                showOlderMessages
                onShowOlderMessages={() => {
                    setActiveBaseMessages(baseMessages)
                    setLoadOlderMessages(true)
                    setIsThreadActive(true)
                }}
                onReply={(reply) => {
                    setActiveBaseMessages(baseMessages)
                    setQueuedReply(reply)
                    setIsThreadActive(true)
                }}
                onDismiss={deleteNode}
            />
        )
    }

    return (
        <NotebookAIChatById
            chatId={chatId}
            cachedTitle={cachedTitle}
            cachedLastAnswer={cachedLastAnswer}
            baseMessages={activeBaseMessages}
            hasLegacyAnswer={hasLegacyAnswer}
            loadOlderMessages={loadOlderMessages}
            queuedReply={queuedReply}
            onShowOlderMessages={() => setLoadOlderMessages(true)}
            onCollapseOlderMessages={() => {
                setActiveBaseMessages(getNotebookAIChatBaseMessages(cachedLastAnswer))
                setLoadOlderMessages(false)
                setQueuedReply(null)
                setIsThreadActive(false)
            }}
            onQueuedReplyConsumed={() => setQueuedReply(null)}
            updateProps={updateProps}
            onDismiss={deleteNode}
        />
    )
}

export function NotebookAIChatById({
    chatId,
    cachedTitle,
    cachedLastAnswer,
    baseMessages,
    hasLegacyAnswer,
    loadOlderMessages,
    queuedReply,
    onShowOlderMessages,
    onCollapseOlderMessages,
    onQueuedReplyConsumed,
    updateProps,
    onDismiss,
}: {
    chatId: string
    cachedTitle: string | null
    cachedLastAnswer: string | null
    baseMessages: NotebookAIChatMessage[]
    hasLegacyAnswer: boolean
    loadOlderMessages: boolean
    queuedReply: string | null
    onShowOlderMessages: () => void
    onCollapseOlderMessages: () => void
    onQueuedReplyConsumed: () => void
    updateProps: (props: Partial<NotebookComponentProps>) => void
    onDismiss: () => void
}): JSX.Element {
    const panelId = getInlineNotebookAIPanelId(chatId, loadOlderMessages ? 'full' : 'inline')
    const maxLogicProps = useMemo<maxLogicType['props']>(
        () => ({ panelId, initialFrontendConversationId: chatId, syncUrl: false }),
        [chatId, panelId]
    )
    const maxLogicInstance = maxLogic(maxLogicProps)
    useMountedLogic(maxLogicInstance)

    const { setConversationId } = useActions(maxLogicInstance)
    const { loadConversation } = useActions(maxGlobalLogic)
    const { threadLogicProps } = useValues(maxLogicInstance)

    useEffect(() => {
        if (loadOlderMessages) {
            setConversationId(chatId)
            loadConversation(chatId)
            return
        }

        const timeout = window.setTimeout(() => {
            if (!maxLogicInstance.values.conversationId && maxLogicInstance.values.activeStreamingThreads === 0) {
                setConversationId(chatId)
            }
        }, 1500)
        return () => window.clearTimeout(timeout)
    }, [chatId, loadConversation, loadOlderMessages, maxLogicInstance, setConversationId])

    if (threadLogicProps.conversationId !== chatId) {
        return (
            <NotebookAIChatConversation
                messages={[{ role: 'thinking', id: 'notebook-ai-chat-loading', content: 'Thinking ...' }]}
                canReply={false}
                showOlderMessages={false}
            />
        )
    }

    return (
        <NotebookAIChatThread
            chatId={chatId}
            threadLogicProps={{ ...threadLogicProps, skipInitialLoad: !loadOlderMessages }}
            cachedTitle={cachedTitle}
            cachedLastAnswer={cachedLastAnswer}
            baseMessages={baseMessages}
            hasLegacyAnswer={hasLegacyAnswer}
            loadOlderMessages={loadOlderMessages}
            queuedReply={queuedReply}
            onShowOlderMessages={onShowOlderMessages}
            onCollapseOlderMessages={onCollapseOlderMessages}
            onQueuedReplyConsumed={onQueuedReplyConsumed}
            updateProps={updateProps}
            onDismiss={onDismiss}
        />
    )
}

export function NotebookAIChatThread({
    chatId,
    threadLogicProps,
    cachedTitle,
    cachedLastAnswer,
    baseMessages,
    hasLegacyAnswer,
    loadOlderMessages,
    queuedReply,
    onShowOlderMessages,
    onCollapseOlderMessages,
    onQueuedReplyConsumed,
    updateProps,
    onDismiss,
}: {
    chatId: string
    threadLogicProps: MaxThreadLogicProps
    cachedTitle: string | null
    cachedLastAnswer: string | null
    baseMessages: NotebookAIChatMessage[]
    hasLegacyAnswer: boolean
    loadOlderMessages: boolean
    queuedReply: string | null
    onShowOlderMessages: () => void
    onCollapseOlderMessages: () => void
    onQueuedReplyConsumed: () => void
    updateProps: (props: Partial<NotebookComponentProps>) => void
    onDismiss: () => void
}): JSX.Element {
    const threadLogicInstance = maxThreadLogic(threadLogicProps)
    useMountedLogic(threadLogicInstance)

    const { askMax } = useActions(threadLogicInstance)
    const { conversation, threadGrouped, threadLoading, threadRaw } = useValues(threadLogicInstance)
    const runtimeContext = useContext(MarkdownNotebookRuntimeContext)
    const replyUiContext = useMemo(
        () =>
            getNotebookAIChatUIContext({
                notebookShortId: runtimeContext?.notebookShortId ?? null,
                notebookTitle: runtimeContext?.notebookTitle ?? 'Untitled notebook',
                markdown: runtimeContext?.markdown ?? '',
                chatId,
            }),
        [chatId, runtimeContext?.markdown, runtimeContext?.notebookShortId, runtimeContext?.notebookTitle]
    )
    const threadMessages = getNotebookAIChatThreadMessages(threadGrouped, threadLoading)
    const visibleMessages =
        loadOlderMessages && threadMessages.length > 0 ? threadMessages : [...baseMessages, ...threadMessages]
    const isThreadStreaming = threadLoading || visibleMessages.at(-1)?.role === 'thinking'
    const displayMessages = getNotebookAIChatDisplayMessages(visibleMessages, cachedLastAnswer, isThreadStreaming)
    const conversationTitle = getUnknownStringProp(conversation?.title)
    const latestAnswer = getLatestNotebookAIChatAnswer(visibleMessages)
    const isThinking = threadLoading || displayMessages.at(-1)?.role === 'thinking'
    const lastProducedAnswerRef = useRef<string | null>(null)
    const lastProducedTitleRef = useRef<string | null>(null)
    useApplyNotebookArtifactMessages(threadRaw, chatId)

    useEffect(() => {
        if (!queuedReply) {
            return
        }

        askMax(queuedReply, true, replyUiContext)
        onQueuedReplyConsumed()
    }, [askMax, onQueuedReplyConsumed, queuedReply, replyUiContext])

    useEffect(() => {
        const nextProps: Partial<NotebookComponentProps> = {}

        // Only push values this client's thread newly produced. The cached props are shared
        // collaborative state: when another window writes a newer answer, comparing it against
        // this window's stale thread and "correcting" it would clobber the other side's reply
        // and the two windows would revert each other forever.
        if (latestAnswer && latestAnswer !== lastProducedAnswerRef.current) {
            lastProducedAnswerRef.current = latestAnswer
            if (latestAnswer !== cachedLastAnswer) {
                nextProps.lastAnswer = latestAnswer
            }
            if (hasLegacyAnswer) {
                nextProps.answer = undefined
            }
        }
        if (conversationTitle && conversationTitle !== lastProducedTitleRef.current) {
            lastProducedTitleRef.current = conversationTitle
            if (conversationTitle !== cachedTitle) {
                nextProps.title = conversationTitle
            }
        }

        if (Object.keys(nextProps).length > 0) {
            updateProps(nextProps)
        }
    }, [cachedLastAnswer, cachedTitle, conversationTitle, hasLegacyAnswer, latestAnswer, updateProps])

    return (
        <NotebookAIChatConversation
            messages={displayMessages}
            canReply={!isThinking}
            showOlderMessages={!loadOlderMessages && baseMessages.length > 0}
            showCollapseOlderMessages={loadOlderMessages}
            onShowOlderMessages={onShowOlderMessages}
            onCollapseOlderMessages={onCollapseOlderMessages}
            onReply={(reply) => askMax(reply, true, replyUiContext)}
            onDismiss={onDismiss}
        />
    )
}

export function NotebookAIChatAnswer({
    id,
    content,
    compact = false,
}: {
    id: string
    content: string
    compact?: boolean
}): JSX.Element {
    return (
        <div
            className={
                compact
                    ? 'MarkdownNotebook__ai-chat-answer MarkdownNotebook__ai-chat-answer--compact'
                    : 'MarkdownNotebook__ai-chat-answer'
            }
        >
            <MarkdownMessage content={content} id={id} />
        </div>
    )
}

export function NotebookAIChatThinking({ message }: { message: string }): JSX.Element {
    return (
        <div className="MarkdownNotebook__ai-chat-thinking">
            <IconSparkles />
            <span>{message}</span>
        </div>
    )
}

export type NotebookAIChatMessageRole = 'human' | 'assistant' | 'thinking' | 'error'

export type NotebookAIChatMessage = {
    role: NotebookAIChatMessageRole
    content: string
    id?: string
}

export function NotebookAIChatConversation({
    messages,
    canReply,
    showOlderMessages,
    showCollapseOlderMessages = false,
    onShowOlderMessages,
    onCollapseOlderMessages,
    onReply,
    onDismiss,
}: {
    messages: NotebookAIChatMessage[]
    canReply: boolean
    showOlderMessages: boolean
    showCollapseOlderMessages?: boolean
    onShowOlderMessages?: () => void
    onCollapseOlderMessages?: () => void
    onReply?: (reply: string) => void
    onDismiss?: () => void
}): JSX.Element {
    const [isReplying, setIsReplying] = useState(false)
    const [reply, setReply] = useState('')
    const scrollRef = useRef<HTMLDivElement>(null)
    const replyText = reply.trim()
    const canSubmit = canReply && !!replyText && !!onReply
    const messageFingerprint = messages
        .map((message) => `${message.role}:${message.id ?? ''}:${message.content}`)
        .join('|')

    useEffect(() => {
        const scrollElement = scrollRef.current
        if (!scrollElement) {
            return
        }
        scrollElement.scrollTop = scrollElement.scrollHeight
    }, [messageFingerprint, isReplying])

    const submitReply = useCallback((): void => {
        if (!canSubmit) {
            return
        }

        onReply(replyText)
        setReply('')
        setIsReplying(false)
    }, [canSubmit, onReply, replyText])

    return (
        <div className="MarkdownNotebook__ai-chat" ref={scrollRef}>
            <div className="MarkdownNotebook__ai-chat-messages">
                {messages.map((message, index) => (
                    <NotebookAIChatMessageView
                        key={`${message.role}-${message.id ?? index}`}
                        message={message}
                        fallbackId={`notebook-ai-chat-message-${index}`}
                    />
                ))}
            </div>
            <div className="MarkdownNotebook__ai-chat-footer">
                <div className="MarkdownNotebook__ai-chat-footer-actions">
                    {canReply && !isReplying && onReply ? (
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            icon={<IconMessage />}
                            onClick={() => setIsReplying(true)}
                        >
                            Reply
                        </LemonButton>
                    ) : null}
                    {showOlderMessages && onShowOlderMessages ? (
                        <LemonButton size="xsmall" type="secondary" onClick={onShowOlderMessages}>
                            Show older messages
                        </LemonButton>
                    ) : null}
                    {showCollapseOlderMessages && onCollapseOlderMessages ? (
                        <LemonButton size="xsmall" type="secondary" onClick={onCollapseOlderMessages}>
                            Collapse older messages
                        </LemonButton>
                    ) : null}
                    {canReply && !isReplying && onDismiss ? (
                        <LemonButton size="xsmall" type="secondary" onClick={onDismiss}>
                            Dismiss
                        </LemonButton>
                    ) : null}
                </div>
                {canReply && isReplying && onReply ? (
                    <div className="MarkdownNotebook__ai-chat-reply">
                        <LemonTextArea
                            className="MarkdownNotebook__ai-chat-reply-input"
                            value={reply}
                            onChange={setReply}
                            onPressEnter={submitReply}
                            onBlur={() => {
                                if (!reply.trim()) {
                                    setIsReplying(false)
                                }
                            }}
                            placeholder="Reply..."
                            minRows={2}
                            maxRows={6}
                            autoFocus
                            stopPropagation
                        />
                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<IconSend />}
                            onClick={submitReply}
                            disabledReason={canSubmit ? undefined : 'Write a reply first'}
                        >
                            Send
                        </LemonButton>
                    </div>
                ) : null}
            </div>
        </div>
    )
}

export function NotebookAIChatMessageView({
    message,
    fallbackId,
}: {
    message: NotebookAIChatMessage
    fallbackId: string
}): JSX.Element {
    if (message.role === 'human') {
        return <div className="MarkdownNotebook__ai-chat-human-message">{message.content}</div>
    }
    if (message.role === 'thinking') {
        return <NotebookAIChatThinking message={message.content} />
    }
    if (message.role === 'error') {
        return <div className="MarkdownNotebook__ai-chat-error">{message.content}</div>
    }
    return <NotebookAIChatAnswer id={message.id ?? fallbackId} content={message.content} compact />
}

export function getNotebookAIChatBaseMessages(cachedLastAnswer: string | null): NotebookAIChatMessage[] {
    if (cachedLastAnswer) {
        return [{ role: 'assistant', id: 'notebook-ai-chat-cached-answer', content: cachedLastAnswer }]
    }
    return []
}

/**
 * What the chat block renders. A collaborator's client has no local thread for a chat
 * another user is driving, but the answer streams in through the Chat node's `lastAnswer`
 * prop — render that live instead of a stuck "Thinking ..." placeholder. The same applies
 * when this client's thread is idle and a different answer arrives through the props
 * (someone replied from another window): it shows as the newest message.
 */
export function getNotebookAIChatDisplayMessages(
    visibleMessages: NotebookAIChatMessage[],
    cachedLastAnswer: string | null,
    isThreadStreaming: boolean = false
): NotebookAIChatMessage[] {
    if (!visibleMessages.length) {
        if (cachedLastAnswer) {
            return getNotebookAIChatBaseMessages(cachedLastAnswer)
        }
        return [{ role: 'thinking', id: 'notebook-ai-chat-loading', content: 'Thinking ...' }]
    }

    if (!isThreadStreaming && cachedLastAnswer && getLatestNotebookAIChatAnswer(visibleMessages) !== cachedLastAnswer) {
        return [
            ...visibleMessages,
            { role: 'assistant', id: 'notebook-ai-chat-remote-answer', content: cachedLastAnswer },
        ]
    }

    return visibleMessages
}

export function getNotebookAIChatThreadMessages(
    threadGrouped: ThreadMessage[],
    threadLoading: boolean
): NotebookAIChatMessage[] {
    const messages = threadGrouped.flatMap((message, index): NotebookAIChatMessage[] => {
        const id = getThreadMessageId(message, index)
        const content = getMessageContent(message)

        if (message.type === AssistantMessageType.Human && content.trim()) {
            return [{ role: 'human', id, content }]
        }
        if (message.type === AssistantMessageType.Failure || message.status === 'error') {
            return [{ role: 'error', id, content: content || 'PostHog AI could not finish this request.' }]
        }
        if (message.type === AssistantMessageType.Notebook && message.status === 'completed') {
            return [{ role: 'assistant', id, content: 'Updated the notebook.' }]
        }
        if (isCompletedNotebookApplicableArtifactMessage(message)) {
            return [{ role: 'assistant', id, content: 'Updated the notebook.' }]
        }
        if (message.type === AssistantMessageType.Assistant) {
            if (content.trim()) {
                return [{ role: 'assistant', id, content }]
            }

            // Thinking metadata is only a live status indicator: a completed message that carries
            // nothing but internal reasoning must not render, or the chat looks stuck thinking.
            if (message.status === 'loading') {
                const thinkingMessage = getThinkingMessage(message)
                return [
                    {
                        role: 'thinking',
                        id,
                        content: getInlineAIStatusText(thinkingMessage ?? undefined, 'Thinking ...'),
                    },
                ]
            }
        }

        return []
    })
    const latestMessage = messages.at(-1)

    if (threadLoading && latestMessage?.role !== 'thinking') {
        const thinkingMessage = [...threadGrouped].reverse().map(getThinkingMessage).find(Boolean)
        messages.push({
            role: 'thinking',
            id: 'notebook-ai-chat-thinking',
            content: getInlineAIStatusText(thinkingMessage ?? undefined, 'Thinking ...'),
        })
    }

    return messages
}

export function getLatestNotebookAIChatAnswer(messages: NotebookAIChatMessage[]): string | null {
    return [...messages].reverse().find((message) => message.role === 'assistant')?.content ?? null
}

export function getThreadMessageId(message: ThreadMessage, index: number): string {
    return 'id' in message && typeof message.id === 'string' ? message.id : `notebook-ai-chat-message-${index}`
}

export function getMessageContent(message: ThreadMessage): string {
    return 'content' in message && typeof message.content === 'string' ? message.content : ''
}

export function getThinkingMessage(message: ThreadMessage): string | null {
    if (message.type !== AssistantMessageType.Assistant) {
        return null
    }

    const thinking = message.meta?.thinking?.find(isThinkingMetadataEntry)
    return thinking?.thinking ?? null
}

export function isThinkingMetadataEntry(entry: unknown): entry is { type: 'thinking'; thinking: string } {
    if (!entry || typeof entry !== 'object') {
        return false
    }

    const metadataEntry = entry as { type?: unknown; thinking?: unknown }
    return metadataEntry.type === 'thinking' && typeof metadataEntry.thinking === 'string'
}
