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
        saveMessagesToLocalStorage: () => true,
        getResponseFromMax: () => true,
        sendBadMessageRating: (messageIndex: number) => ({ messageIndex }),
        closeChat: () => true,
        openChat: () => true,
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
    forms: ({ actions }) => ({
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
                actions.addMessage({
                    role: 'user',
                    content: message,
                })
                actions.setIsMaxResponseLoading(true)
                actions.setErrorSubmittingMessage(false)
                actions.resetSendChatMessage()
                actions.getResponseFromMax()
                return true
            },
        },
    }),
    listeners: ({ actions, values }) => ({
        saveMessagesToLocalStorage: () => {
            const expirationDate = new Date()
            expirationDate.setDate(expirationDate.getDate() + 1) // Expires in 1 day
            localStorage.setItem(
                'max-ai-messages',
                JSON.stringify({ messages: values.messages, expiration: expirationDate.getTime() })
            )
        },
        closeChat: () => {
            actions.setIsChatActive(false)
            localStorage.setItem('max-ai-chat-closed', JSON.stringify(1))
        },
        openChat: () => {
            actions.setIsChatActive(true)
            localStorage.removeItem('max-ai-chat-closed')
        },
        getResponseFromMax: async () => {
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
                    actions.saveMessagesToLocalStorage()
                })
                .catch((err) => {
                    console.log(err)
                    actions.setIsMaxResponseLoading(false)
                    actions.setErrorSubmittingMessage(true)
                })
        },
        sendBadMessageRating: async ({ messageIndex }) => {
            const newMessages = values.messages
            newMessages[messageIndex].ratingValue = 'bad'
            actions.setMessages(newMessages)
            actions.addMessage({
                role: 'assistant',
                content: `Whoops, sorry my response wasn't what you were looking for. I will pass this feedback on to the team and will attempt to re-generate a better response for you.\n\nYou can also send an email to hey@posthog.com to get in touch with a human.`,
                responseTo: 'rating',
            })
            actions.setIsMaxResponseLoading(true)
            actions.getResponseFromMax()
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            // get messages from storage, if there are any
            const messagesInStorage = localStorage.getItem('max-ai-messages')
            const chatClosedInStorage = localStorage.getItem('max-ai-chat-closed')
            if (messagesInStorage) {
                const messagesInStorageJSON = JSON.parse(messagesInStorage)
                if (
                    messagesInStorageJSON &&
                    messagesInStorageJSON.messages.length > 1 &&
                    messagesInStorageJSON.expiration > Date.now()
                ) {
                    actions.setMessages(messagesInStorageJSON.messages)
                    if (!chatClosedInStorage) {
                        actions.setIsChatActive(true)
                    }
                }
            }
        },
    }),
})
