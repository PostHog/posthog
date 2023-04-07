import { kea } from 'kea'
import type { maxAILogicType } from './maxAILogicType'
import { ChatMessageType } from '~/types'

const defaultMessage: ChatMessageType = {
    role: 'assistant',
    content: "Hi there! I'm Max, your friendly AI support assistant. How can I help you today?",
}

export const maxAILogic = kea<maxAILogicType>({
    path: () => ['lib', 'components', 'MaxAI', 'maxAILogic'],
    actions: () => ({
        setIsChatActive: (isChatActive: boolean) => ({ isChatActive }),
        setMessages: (messages: ChatMessageType[]) => ({ messages }),
        addMessage: (message: ChatMessageType) => ({ message }),
        setIsMaxResponseLoading: (isMaxResponseLoading: boolean) => ({ isMaxResponseLoading }),
        setErrorSubmittingMessage: (errorSubmittingMessage: boolean) => ({ errorSubmittingMessage }),
    }),
    reducers: () => ({
        isChatActive: [
            false,
            {
                setIsChatActive: (_, { isChatActive }) => isChatActive,
            },
        ],
        isMaxResponseLoading: [
            false,
            {
                setIsMaxResponseLoading: (_, { isMaxResponseLoading }) => isMaxResponseLoading,
            },
        ],
        messages: [
            [defaultMessage],
            {
                setMessages: (_, { messages }) => messages,
                addMessage: (state, { message }) => [...state, message],
            },
        ],
        errorSubmittingMessage: [
            false,
            {
                setErrorSubmittingMessage: (_, { errorSubmittingMessage }) => errorSubmittingMessage,
            },
        ],
    }),
    forms: ({ actions, values }) => ({
        sendChatMessage: {
            defaults: {
                message: '',
            },
            errors: ({ message }: { message: string }) => {
                return {
                    message: !message ? 'Please enter a message' : null,
                }
            },
            submit: async ({ message }: { message: string }) => {
                console.log('submitting', message)
                actions.addMessage({
                    role: 'user',
                    content: message,
                })
                console.log(values.messages, 'the messages')
                actions.setIsMaxResponseLoading(true)
                actions.setErrorSubmittingMessage(false)
                actions.resetSendChatMessage()
                await fetch('https://maxfly.posthog.cc/chat', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(values.messages),
                })
                    .then((res) => res.json())
                    .then((res) => {
                        actions.setIsMaxResponseLoading(false)
                        // add the response to the messages
                        actions.addMessage({
                            role: 'assistant',
                            content: res,
                        })
                    })
                    .catch((err) => {
                        console.log(err)
                        actions.setIsMaxResponseLoading(false)
                        actions.setErrorSubmittingMessage(true)
                    })
                return true
            },
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            // TODO: store a cookie if the chat is currently active vs has history and has been closed, so it shouldn't open automatically
            // For now during dev just keep it open
            actions.setIsChatActive(true)
        },
    }),
})
