import { useActions, useMountedLogic, useValues } from 'kea'
import { type ReactNode, useMemo } from 'react'

import { type ChatActionComposer, ChatActionComposerProvider } from 'products/posthog_ai/frontend/api/primitives'

import { maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'

/** Wires the suggested-action buttons in a sandbox thread to the Max panel's own input. */
export function MaxChatActionComposerProvider({ children }: { children: ReactNode }): JSX.Element {
    const threadLogic = useMountedLogic(maxThreadLogic)
    const { question, contextDisabledReason, queueDisabledReason } = useValues(threadLogic)
    const { askMax, setQuestion } = useActions(threadLogic)
    const { focusInput } = useActions(maxLogic)
    const value = useMemo<ChatActionComposer>(
        () => ({
            insert: (message) => {
                // Read at click time: a keystroke that has not rendered yet must not be lost.
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
        }),
        [threadLogic, question, contextDisabledReason, queueDisabledReason, askMax, setQuestion, focusInput]
    )
    return <ChatActionComposerProvider value={value}>{children}</ChatActionComposerProvider>
}
