import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { userLogic } from 'scenes/userLogic'

import { AgentMode } from '~/queries/schema/schema-assistant-messages'
import { Conversation, ConversationQueueMessage } from '~/types'

import { MAX_MESSAGE_LENGTH, MESSAGE_TOO_LONG, messageLength } from '../max-constants'
import { maxGlobalLogic } from '../maxGlobalLogic'
import { maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'
import { MAX_SLASH_COMMANDS } from '../slash-commands'

/**
 * Show the character counter only once the message gets close to the limit. A permanent counter
 * under every composer would be noise: almost every message is a couple of hundred characters.
 */
const LENGTH_COUNTER_THRESHOLD = MAX_MESSAGE_LENGTH * 0.9

export interface QuestionInputController {
    // Draft
    inputValue: string
    handleQuestionChange: (value: string) => void
    hasQuestion: boolean
    fillInHint: string | null
    showFillInHint: boolean
    promptLength: number | null
    isOverLengthLimit: boolean
    maxMessageLength: number
    // Conversation state
    conversation: Conversation | null
    threadLoading: boolean
    inputDisabled: boolean
    isSharedThread: boolean
    streamingActive: boolean
    pendingPrompt: string | null
    dataProcessingAccepted: boolean
    showResearchBanner: boolean
    // Attachments (only offered on a fresh chat while the sandbox flag is on)
    showAttachButton: boolean
    attachmentInputRef: React.RefObject<HTMLInputElement>
    handleAttachmentChange: (event: React.ChangeEvent<HTMLInputElement>) => void
    // Queue
    queueingEnabled: boolean
    queuedMessages: ConversationQueueMessage[]
    displayQueuedMessages: ConversationQueueMessage[]
    queueSubmitting: boolean
    editingQueueId: string | null
    setEditingQueueId: (id: string | null) => void
    saveQueuedMessage: (messageId: string, content: string) => void
    // Send / stop
    isQueueingSubmission: boolean
    showStopButton: boolean
    submissionDisabledReason: string | undefined
    disabledReason: string | undefined
    slashCommandIcon: JSX.Element | undefined
    submit: (prompt: string) => void
    handleSendClick: () => void
    handlePressEnter: () => void
    handleKeyDown: (event: React.KeyboardEvent<HTMLTextAreaElement>) => void
    handleBlur: (event: React.FocusEvent<HTMLTextAreaElement>) => void
    completeThreadGeneration: () => void
    // Slash commands
    showAutocomplete: boolean
    closeAutocomplete: () => void
    // Support / impersonation
    isImpersonatedInternalConversation: boolean
    isImpersonatingExistingConversation: boolean
    supportOverrideEnabled: boolean
    setSupportOverrideEnabled: (enabled: boolean) => void
}

export interface UseQuestionInputOptions {
    textAreaRef?: React.RefObject<HTMLTextAreaElement>
    onSubmit?: () => void
}

/**
 * The behavior of the legacy PostHog AI composer, shared by its lemon and quill skins: the local draft and
 * its debounced sync to kea, the slash-command autocomplete, the fill-in hint, the message queue, the
 * send/stop/queue decision, the length guard, and the sandbox pre-warm release on blur. Each skin only
 * draws what this returns.
 */
export function useQuestionInput({ textAreaRef, onSubmit }: UseQuestionInputOptions): QuestionInputController {
    const { dataProcessingAccepted, isPhaiSandboxFlagOn } = useValues(maxGlobalLogic)
    const { question, fillInHint, typingSuggestion } = useValues(maxLogic)
    const { setQuestion, setFillInHint, cancelSuggestionTyping, attachFilesToNewChat } = useActions(maxLogic)
    const { user } = useValues(userLogic)
    const {
        conversation,
        threadLoading,
        inputDisabled,
        contextDisabledReason,
        queueDisabledReason,
        isSharedThread,
        cancelLoading,
        pendingPrompt,
        isImpersonatingExistingConversation,
        supportOverrideEnabled,
        streamingActive,
        agentMode,
        threadMessageCount,
        queueingEnabled,
        queuedMessages,
        queueSubmitting,
    } = useValues(maxThreadLogic)
    const {
        askMax,
        stopGeneration,
        completeThreadGeneration,
        setSupportOverrideEnabled,
        updateQueuedMessage,
        releaseSandboxPrewarm,
    } = useActions(maxThreadLogic)
    // Show info banner for conversations created during impersonation (marked as internal)
    const isImpersonatedInternalConversation = !!user?.is_impersonated && !!conversation?.is_internal

    const [showAutocomplete, setShowAutocomplete] = useState(false)
    // Tracks an explicit dismissal (e.g. Esc) so the popover stays closed while the
    // user keeps typing a message that still starts with "/". "/" + Esc is a valid path.
    const [autocompleteDismissed, setAutocompleteDismissed] = useState(false)
    const [editingQueueId, setEditingQueueId] = useState<string | null>(null)
    const displayQueuedMessages = useMemo(() => [...queuedMessages].reverse(), [queuedMessages])

    // Hold the textarea value in local state so each keystroke is an isolated, cheap re-render
    // rather than a global kea dispatch. Binding the input directly to kea made every keystroke
    // notify every store subscriber, so input lag grew with conversation length (more mounted
    // messages = more subscriptions to sweep). kea remains the source of truth for submit, slash
    // commands, and draft persistence — we sync to it on a debounce, immediately for slash
    // commands so the autocomplete stays responsive, and on submit/blur.
    const attachmentInputRef = useRef<HTMLInputElement>(null)
    const [inputValue, setInputValue] = useState(question)
    const debouncedSetQuestion = useDebouncedCallback((value: string) => setQuestion(value), 150)

    // Flush any pending debounce when the component unmounts so that a draft typed just
    // before programmatic navigation (no blur event) is still persisted to kea.
    useEffect(() => {
        return () => debouncedSetQuestion.flush()
    }, [debouncedSetQuestion])

    // Mirror external question changes (draft restore, slash command insertion, clear on submit)
    // back into local state. Writing the same value is a no-op, so the debounced sync below
    // doesn't cause an extra render.
    useEffect(() => {
        setInputValue(question)
    }, [question])

    const handleQuestionChange = (value: string): void => {
        setInputValue(value)
        // The user typing their own text ends the fill-in cue.
        if (fillInHint) {
            setFillInHint(null)
        }
        if (value.startsWith('/')) {
            // Slash commands drive the autocomplete off kea's `question`, so sync immediately.
            debouncedSetQuestion.cancel()
            setQuestion(value)
        } else {
            debouncedSetQuestion(value)
        }
    }

    const submit = (prompt: string): void => {
        // askMax reads the prompt arg directly and clears `question` afterwards, so drop any
        // pending debounce to stop it from re-populating the just-sent text.
        debouncedSetQuestion.cancel()
        // A suggestion is still typing itself in. The user picked that suggestion, so send all of
        // it rather than the prefix that happens to be on screen, and stop the animation writing
        // the rest into the composer after the message has gone.
        const content = typingSuggestion ?? prompt
        if (typingSuggestion) {
            cancelSuggestionTyping()
        }
        if (fillInHint) {
            setFillInHint(null)
        }
        askMax(content)
    }

    // Counting code points is O(n), so only pay for it near the limit. A string's UTF-16 length is
    // never below its code point count, so a shorter one can't be over the limit.
    const promptLength = useMemo(
        () => (inputValue.length >= LENGTH_COUNTER_THRESHOLD ? messageLength(inputValue) : null),
        [inputValue]
    )
    const isOverLengthLimit = promptLength !== null && promptLength > MAX_MESSAGE_LENGTH

    const hasQuestion = inputValue.trim().length > 0
    // A fill-in suggestion typed its prefix in and is waiting for the user to complete it.
    const showFillInHint = !!fillInHint
    const isQueueingSubmission = queueingEnabled && threadLoading && hasQuestion
    const showStopButton = threadLoading && !isQueueingSubmission && !cancelLoading

    // Mirrors maxThreadLogic's `submissionDisabledReason` selector, but using the local input
    // value so the submit guard stays correct while the debounced sync to kea is still pending.
    const submissionDisabledReason = contextDisabledReason
        ? contextDisabledReason
        : !inputValue
          ? 'I need some input first'
          : isOverLengthLimit
            ? MESSAGE_TOO_LONG
            : queueDisabledReason

    // Update autocomplete visibility when the input changes
    useEffect(() => {
        const isSlashCommand = inputValue[0] === '/'
        // Once the input is no longer a slash command, clear any prior dismissal so
        // typing "/" again later reopens the popover.
        if (!isSlashCommand && autocompleteDismissed) {
            setAutocompleteDismissed(false)
        }
        const shouldShow = isSlashCommand && !autocompleteDismissed
        if (shouldShow && !showAutocomplete) {
            posthog.capture('Max slash command autocomplete shown') // [PostHog] Event: "Max slash command autocomplete shown"
        }
        setShowAutocomplete(shouldShow)
    }, [inputValue, showAutocomplete, autocompleteDismissed])

    let disabledReason = submissionDisabledReason
    if (threadLoading && !isQueueingSubmission) {
        disabledReason = undefined
    }
    if (cancelLoading) {
        disabledReason = 'Cancelling...'
    }

    useEffect(() => {
        if (!streamingActive && textAreaRef?.current) {
            textAreaRef.current.focus()
        }
    }, [streamingActive]) // oxlint-disable-line react-hooks/exhaustive-deps

    const closeAutocomplete = (): void => {
        setShowAutocomplete(false)
        setAutocompleteDismissed(true)
    }

    const handleBlur = (e: React.FocusEvent<HTMLTextAreaElement>): void => {
        debouncedSetQuestion.flush()
        // Release any sandbox pre-warm when the user leaves the
        // input without sending. No-op on LangGraph / unwarmed
        // conversations.
        //
        // But clicking the send button blurs the textarea *before*
        // its onClick fires the send — releasing here would cancel
        // the very warm Run the send is about to consume. When focus
        // moves to the send button, skip the release and let the send
        // path consume the warm (it does so without a DELETE).
        const next = e.relatedTarget as HTMLElement | null
        if (next?.closest('[data-attr="max-send-message"]')) {
            return
        }
        releaseSandboxPrewarm()
    }

    const handlePressEnter = (): void => {
        if (hasQuestion && !submissionDisabledReason && (!threadLoading || queueingEnabled)) {
            onSubmit?.()
            submit(inputValue)
        }
    }

    const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>): void => {
        if (event.key === 'ArrowUp' && !inputValue.trim() && queuedMessages.length > 0 && !editingQueueId) {
            const target = event.currentTarget
            const atStart = target.selectionStart === 0 && target.selectionEnd === 0
            const isSingleLine = target.value.split('\n').length <= 1
            if (!atStart || !isSingleLine) {
                return
            }
            const nextMessageId = queuedMessages[0]?.id
            if (!nextMessageId) {
                return
            }
            event.preventDefault()
            setEditingQueueId(nextMessageId)
        }
    }

    const handleSendClick = (): void => {
        if (threadLoading) {
            if (isQueueingSubmission) {
                if (submissionDisabledReason) {
                    textAreaRef?.current?.focus()
                    return
                }
                submit(inputValue)
                return
            }
            stopGeneration()
            return
        }
        if (submissionDisabledReason) {
            textAreaRef?.current?.focus()
            return
        }
        submit(inputValue)
    }

    const handleAttachmentChange = (event: React.ChangeEvent<HTMLInputElement>): void => {
        const files = Array.from(event.target.files ?? [])
        event.target.value = ''
        attachFilesToNewChat(files, inputValue)
    }

    const saveQueuedMessage = (messageId: string, content: string): void => {
        updateQueuedMessage(messageId, content)
        setEditingQueueId(null)
    }

    const slashCommandIcon = MAX_SLASH_COMMANDS.find((cmd) => cmd.name === inputValue.split(' ', 1)[0])?.icon

    return {
        // Draft
        inputValue,
        handleQuestionChange,
        hasQuestion,
        fillInHint,
        showFillInHint,
        promptLength,
        isOverLengthLimit,
        maxMessageLength: MAX_MESSAGE_LENGTH,
        // Conversation state
        conversation,
        threadLoading,
        inputDisabled,
        isSharedThread,
        streamingActive,
        pendingPrompt,
        dataProcessingAccepted,
        showResearchBanner: agentMode === AgentMode.Research && threadMessageCount === 0,
        // Attachments (only offered on a fresh chat while the sandbox flag is on)
        showAttachButton: isPhaiSandboxFlagOn && !conversation,
        attachmentInputRef,
        handleAttachmentChange,
        // Queue
        queueingEnabled,
        queuedMessages,
        displayQueuedMessages,
        queueSubmitting,
        editingQueueId,
        setEditingQueueId,
        saveQueuedMessage,
        // Send / stop
        isQueueingSubmission,
        showStopButton,
        submissionDisabledReason,
        disabledReason,
        slashCommandIcon,
        submit,
        handleSendClick,
        handlePressEnter,
        handleKeyDown,
        handleBlur,
        completeThreadGeneration,
        // Slash commands
        showAutocomplete,
        closeAutocomplete,
        // Support / impersonation
        isImpersonatedInternalConversation,
        isImpersonatingExistingConversation,
        supportOverrideEnabled,
        setSupportOverrideEnabled,
    }
}

export interface QueuedMessageEditProps {
    message: ConversationQueueMessage
    isEditing: boolean
    onEdit: () => void
    onCancel: () => void
    onSave: (messageId: string, content: string) => void
}
