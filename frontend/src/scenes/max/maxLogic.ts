import { actions, kea, listeners, path, reducers } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

import type { maxLogicType } from './maxLogicType'

export interface ThreadMessage {
    role: 'user' | 'assistant'
    content: string
}

export const maxLogic = kea<maxLogicType>([
    path(['scenes', 'max', 'maxLogic']),
    actions({
        askMax: (prompt: string) => ({ prompt }),
        addMessage: (message: ThreadMessage) => ({ message }),
        replaceMessages: (messages: ThreadMessage[]) => ({ messages }),
    }),
    reducers({
        thread: [
            [] as ThreadMessage[],
            {
                addMessage: (state, { message }) => {
                    return [...state, message]
                },
                replaceMessages: (_, { messages }) => {
                    return messages
                },
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        askMax: ({ prompt }) =>
            new Promise<void>((resolve) => {
                const url = new URL(`/api/projects/${teamLogic.values.currentTeamId}/query/chat/`, location.origin)
                url.searchParams.append('prompt', prompt)
                url.searchParams.append('thread', JSON.stringify(values.thread))
                actions.addMessage({ role: 'user', content: prompt })
                const source = new window.EventSource(url.toString())
                source.onerror = (e) => {
                    console.error('Failed to poll chat: ', e)
                }
                source.onmessage = (event: any) => {
                    const eventData = JSON.parse(event.data)

                    if (!Object.keys(eventData).length) {
                        // An empty object is the termination signal
                        source.close()
                        resolve()
                    } else {
                        actions.replaceMessages(eventData)
                    }
                }
            }),
    })),
])
