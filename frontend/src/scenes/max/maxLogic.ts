import { actions, kea, listeners, path, props, reducers } from 'kea'
import api from 'lib/api'

import { ExperimentalAITrendsQuery } from '~/queries/schema'

import type { maxLogicType } from './maxLogicType'

interface MaxLogicProps {
    sessionId: string
}

interface TrendGenerationResult {
    reasoning_steps?: string[]
    answer?: ExperimentalAITrendsQuery
}

export interface ThreadMessage {
    role: 'user' | 'assistant'
    content: string | TrendGenerationResult
}

export const maxLogic = kea<maxLogicType>([
    path(['scenes', 'max', 'maxLogic']),
    props({} as MaxLogicProps),
    actions({
        askMax: (prompt: string) => ({ prompt }),
        askMaxSuccess: true,
        addMessage: (message: ThreadMessage) => ({ message }),
        replaceMessage: (index: number, message: ThreadMessage) => ({ index, message }),
    }),
    reducers({
        thread: [
            [] as ThreadMessage[],
            {
                addMessage: (state, { message }) => [...state, message],
                replaceMessage: (state, { message, index }) => [
                    ...state.slice(0, index),
                    message,
                    ...state.slice(index + 1),
                ],
            },
        ],
        threadLoading: [
            false,
            {
                askMax: () => true,
                askMaxSuccess: () => false,
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        askMax: async ({ prompt }) => {
            actions.addMessage({ role: 'user', content: prompt })
            const newIndex = values.thread.length

            const response = await api.chat({
                session_id: props.sessionId,
                messages: values.thread,
            })
            const reader = response.body?.getReader()
            const decoder = new TextDecoder()

            if (reader) {
                let firstChunk = true

                while (true) {
                    const { done, value } = await reader.read()
                    if (done) {
                        break
                    }

                    const text = decoder.decode(value)
                    const parsedResponse = parseResponse(text)

                    if (firstChunk) {
                        firstChunk = false

                        if (parsedResponse) {
                            actions.addMessage({ role: 'assistant', content: parsedResponse })
                        }
                    } else if (parsedResponse) {
                        actions.replaceMessage(newIndex, { role: 'assistant', content: parsedResponse })
                    }
                }
            }

            actions.askMaxSuccess()
        },
    })),
])

/**
 * Parses the generation result from the API. Some generation chunks might be sent in batches.
 * @param response
 */
function parseResponse(response: string, recursive = true): TrendGenerationResult | null {
    try {
        const parsed = JSON.parse(response)
        return parsed as TrendGenerationResult
    } catch {
        if (!recursive) {
            return null
        }

        const results: [number, number][] = []
        let pair: [number, number] = [0, 0]
        let seq = 0

        for (let i = 0; i < response.length; i++) {
            const char = response[i]

            if (char === '{') {
                if (seq === 0) {
                    pair[0] = i
                }

                seq += 1
            }

            if (char === '}') {
                seq -= 1
                if (seq === 0) {
                    pair[1] = i
                }
            }

            if (seq === 0) {
                results.push(pair)
                pair = [0, 0]
            }
        }

        const lastPair = results.pop()

        if (lastPair) {
            const [left, right] = lastPair
            return parseResponse(response.slice(left, right + 1), false)
        }

        return null
    }
}
