import { createParser } from 'eventsource-parser'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { uuid } from 'lib/utils'
import { urls } from 'scenes/urls'

import { AssistantEventType, AssistantMessageType } from '~/queries/schema/schema-assistant-messages'

import type { searchAiPreviewLogicType } from './searchAiPreviewLogicType'
import { SearchItem, SearchLogicProps, searchLogic } from './searchLogic'
import { shouldSkipAiHighlight } from './shouldSkipAiHighlight'

export type StreamingState = 'idle' | 'streaming' | 'done' | 'error'

export interface SearchAiPreviewLogicProps {
    logicKey: SearchLogicProps['logicKey']
}

const PREVIEW_MAX_LENGTH = 300

export const searchAiPreviewLogic = kea<searchAiPreviewLogicType>([
    path((key) => ['lib', 'components', 'Search', 'searchAiPreviewLogic', key]),
    props({} as SearchAiPreviewLogicProps),
    key((props) => props.logicKey),

    connect((props: SearchAiPreviewLogicProps) => ({
        values: [
            searchLogic({ logicKey: props.logicKey }),
            ['search', 'allCategories'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    })),

    actions({
        triggerAiPreview: (query: string) => ({ query }),
        setPreviewContent: (text: string) => ({ text }),
        setConversationId: (conversationId: string) => ({ conversationId }),
        setStreamingState: (state: StreamingState) => ({ state }),
        cancelPreview: true,
        resetPreview: true,
    }),

    reducers({
        previewContent: [
            '',
            {
                setPreviewContent: (_, { text }) => text,
                resetPreview: () => '',
                cancelPreview: () => '',
            },
        ],
        conversationId: [
            null as string | null,
            {
                setConversationId: (_, { conversationId }) => conversationId,
                resetPreview: () => null,
            },
        ],
        streamingState: [
            'idle' as StreamingState,
            {
                triggerAiPreview: () => 'streaming' as StreamingState,
                setStreamingState: (_, { state }) => state,
                resetPreview: () => 'idle' as StreamingState,
                cancelPreview: () => 'idle' as StreamingState,
            },
        ],
        lastQuery: [
            '',
            {
                triggerAiPreview: (_, { query }) => query,
                resetPreview: () => '',
            },
        ],
    }),

    selectors({
        showPreview: [
            (s) => [s.streamingState, s.previewContent],
            (streamingState, previewContent): boolean =>
                streamingState === 'streaming' || (streamingState === 'done' && previewContent.length > 0),
        ],
        truncatedPreviewText: [
            (s) => [s.previewContent],
            (previewContent): string => {
                if (previewContent.length <= PREVIEW_MAX_LENGTH) {
                    return previewContent
                }
                const truncated = previewContent.substring(0, PREVIEW_MAX_LENGTH)
                const lastSpace = truncated.lastIndexOf(' ')
                return (lastSpace > PREVIEW_MAX_LENGTH * 0.8 ? truncated.substring(0, lastSpace) : truncated) + '…'
            },
        ],
        aiConversationUrl: [
            (s) => [s.conversationId, s.lastQuery],
            (conversationId, lastQuery): string =>
                conversationId ? urls.ai(conversationId) : urls.ai(undefined, lastQuery),
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        triggerAiPreview: async ({ query }, breakpoint) => {
            cache.abortController?.abort()

            const trimmedQuery = query.trim()
            if (trimmedQuery.length < 5) {
                actions.resetPreview()
                return
            }

            // Only stream for question-like queries: if shouldSkipAiHighlight returns true,
            // the query is navigational and we should NOT stream
            const realItems: SearchItem[] = values.allCategories.flatMap((cat) => cat.items)
            if (shouldSkipAiHighlight(trimmedQuery, realItems)) {
                actions.resetPreview()
                return
            }

            await breakpoint(800)

            cache.abortController = new AbortController()
            const traceId = uuid()
            const conversationId = uuid()
            actions.setConversationId(conversationId)

            try {
                const response = await api.conversations.stream(
                    {
                        content: trimmedQuery,
                        trace_id: traceId,
                        conversation: conversationId,
                    },
                    { signal: cache.abortController.signal }
                )

                const reader = response.body?.getReader()
                if (!reader) {
                    actions.setStreamingState('error')
                    return
                }

                const decoder = new TextDecoder()
                const parser = createParser({
                    onEvent: ({ data, event }) => {
                        if (event === AssistantEventType.Conversation) {
                            try {
                                const parsed = JSON.parse(data)
                                if (parsed?.id) {
                                    actions.setConversationId(parsed.id)
                                }
                            } catch {
                                // ignore parse errors
                            }
                        } else if (event === AssistantEventType.Message) {
                            try {
                                const parsed = JSON.parse(data)
                                if (parsed?.type === AssistantMessageType.Assistant && parsed?.content) {
                                    actions.setPreviewContent(parsed.content)
                                }
                            } catch {
                                // ignore parse errors
                            }
                        }
                    },
                })

                while (true) {
                    const { done, value } = await reader.read()
                    parser.feed(decoder.decode(value))
                    if (done) {
                        break
                    }
                }

                actions.setStreamingState('done')
            } catch (e) {
                if (e instanceof DOMException && e.name === 'AbortError') {
                    return
                }
                actions.setStreamingState('error')
            }

            cache.abortController = undefined
        },

        cancelPreview: () => {
            cache.abortController?.abort()
            cache.abortController = undefined
        },

        resetPreview: () => {
            cache.abortController?.abort()
            cache.abortController = undefined
        },
    })),

    subscriptions(({ actions, values }) => ({
        search: (search: string) => {
            if (!values.featureFlags[FEATURE_FLAGS.SEARCH_AI_PREVIEW]) {
                return
            }
            if (!search.trim()) {
                actions.resetPreview()
                return
            }
            actions.cancelPreview()
            actions.triggerAiPreview(search)
        },
    })),
])
