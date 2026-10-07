import { useActions, useMountedLogic, useValues } from 'kea'
import { type ReactNode, useMemo } from 'react'

import {
    type ChatActionComposer,
    ChatActionComposerProvider,
    PENDING_REQUEST_REASON,
} from 'products/posthog_ai/frontend/api/primitives'

import { maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'

/**
 * Wires the suggested-action buttons in a sandbox thread to the Max panel's own input. Another user's
 * shared conversation has no input, so it gets no composer and the buttons render disabled.
 */
export function MaxChatActionComposerProvider({ children }: { children: ReactNode }): JSX.Element {
    const threadLogic = useMountedLogic(maxThreadLogic)
    const { question, contextDisabledReason, queueDisabledReason, isSharedThread, pendingSandboxPermissionRequest } =
        useValues(threadLogic)
    const { askMax, setQuestion } = useActions(threadLogic)
    const { focusInput } = useActions(maxLogic)
    const value = useMemo<ChatActionComposer | null>(() => {
        if (isSharedThread) {
            return null
        }
        return {
            insert: (message) => {
                const current: string = threadLogic.values.question
                setQuestion(current.trim() ? `${current.trimEnd()}\n${message}` : message)
                focusInput()
            },
            send: (message) => askMax(message),
            sendDisabledReason:
                contextDisabledReason ??
                (question.trim() ? 'Send or clear your draft first' : null) ??
                queueDisabledReason ??
                null,
            insertDisabledReason: pendingSandboxPermissionRequest ? PENDING_REQUEST_REASON : null,
        }
    }, [
        isSharedThread,
        threadLogic,
        question,
        contextDisabledReason,
        queueDisabledReason,
        pendingSandboxPermissionRequest,
        askMax,
        setQuestion,
        focusInput,
    ])
    return <ChatActionComposerProvider value={value}>{children}</ChatActionComposerProvider>
}
