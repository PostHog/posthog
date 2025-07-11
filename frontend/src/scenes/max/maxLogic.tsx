import { IconBook, IconGraph, IconHogQL, IconPlug, IconRewindPlay } from '@posthog/icons'
import { actions, afterMount, connect, defaults, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, decodeParams, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { objectsEqual, uuid } from 'lib/utils'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import { maxSettingsLogic } from 'scenes/settings/environment/maxSettingsLogic'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { actionsModel } from '~/models/actionsModel'
import { productUrls } from '~/products'
import { RootAssistantMessage } from '~/queries/schema/schema-assistant-messages'
import { Conversation, ConversationDetail, ConversationStatus, SidePanelTab } from '~/types'

import { maxContextLogic } from './maxContextLogic'
import { maxGlobalLogic } from './maxGlobalLogic'
import type { maxLogicType } from './maxLogicType'

export type MessageStatus = 'loading' | 'completed' | 'error'

export type ThreadMessage = RootAssistantMessage & {
    status: MessageStatus
}

export interface SuggestionItem {
    content: string
}

export interface SuggestionGroup {
    label: string
    icon: JSX.Element
    suggestions: SuggestionItem[]
    url?: string
    tooltip?: string
}

const HEADLINES = [
    'How can I help you build?',
    'What are you curious about?',
    'How can I help you understand users?',
    'What do you want to know today?',
]

export const maxLogic = kea<maxLogicType>([
    path(['scenes', 'max', 'maxLogic']),

    connect(() => ({
        values: [
            maxGlobalLogic,
            ['dataProcessingAccepted', 'tools'],
            maxSettingsLogic,
            ['coreMemory'],
            // Actions are lazy-loaded. In order to display their names in the UI, we're loading them here.
            actionsModel({ params: 'include_count=1' }),
            ['actions'],
        ],
        actions: [maxContextLogic, ['resetContext']],
    })),

    actions({
        setQuestion: (question: string) => ({ question }),
        scrollThreadToBottom: (behavior?: 'instant' | 'smooth') => ({ behavior }),
        setConversationId: (conversationId: string) => ({ conversationId }),
        startNewConversation: true,
        toggleConversationHistory: (visible?: boolean) => ({ visible }),
        loadThread: (conversation: ConversationDetail) => ({ conversation }),
        pollConversation: (
            conversationId: string,
            currentRecursionDepth: number = 0,
            leadingTimeout: number = 2500
        ) => ({
            conversationId,
            currentRecursionDepth,
            leadingTimeout,
        }),
        goBack: true,
        setBackScreen: (screen: 'history') => ({ screen }),
        focusInput: true,
        setActiveGroup: (group: SuggestionGroup | null) => ({ group }),
        setActiveStreamingThreads: (inc: 1 | -1) => ({ inc }),
        setAutoRun: (autoRun: boolean) => ({ autoRun }),
        /**
         * Save the logic ID for a conversation ID in a cache.
         */
        setThreadKey: (conversationId: string, logicKey: string) => ({ conversationId, logicKey }),

        /**
         * Prepend a conversation to the conversation history or update it in place.
         */
        prependOrReplaceConversation: (conversation: ConversationDetail | Conversation) => ({ conversation }),
    }),

    defaults({
        conversationHistory: [] as ConversationDetail[],
    }),

    reducers({
        activeStreamingThreads: [
            0,
            {
                setActiveStreamingThreads: (state, { inc }) => Math.max(state + inc, 0),
            },
        ],

        question: [
            '',
            {
                setQuestion: (_, { question }) => question,
                startNewConversation: () => '',
            },
        ],

        conversationId: [
            null as string | null,
            {
                setConversationId: (_, { conversationId }) => conversationId,
                startNewConversation: () => null,
                toggleConversationHistory: (state, { visible }) => (visible ? null : state),
            },
        ],

        // The shadow ID for the temporary conversations that have started streaming, but didn't receive a conversation object yet.
        tempConversationId: [
            generateTempId(),
            {
                startNewConversation: () => generateTempId(),
                setConversationId: () => generateTempId(),
            },
        ],

        conversationHistoryVisible: [
            false,
            {
                toggleConversationHistory: (state, { visible }) => visible ?? !state,
                startNewConversation: () => false,
            },
        ],

        backToScreen: [
            null as 'history' | null,
            {
                setBackScreen: (_, { screen }) => screen,
                startNewConversation: () => null,
            },
        ],

        /**
         * When the focus counter updates, the input component will rerender and refocus the input.
         */
        focusCounter: [0, { focusInput: (state) => state + 1 }],

        activeSuggestionGroup: [
            null as SuggestionGroup | null,
            {
                setActiveGroup: (_, { group }) => group,
            },
        ],

        /**
         * Identifies the logic ID for each conversation ID.
         */
        threadKeys: [
            {} as Record<string, string>,
            {
                setThreadKey: (state, { conversationId, logicKey }) => ({ ...state, [conversationId]: logicKey }),
            },
        ],

        conversationHistory: {
            prependOrReplaceConversation: (state, { conversation }) => {
                return mergeConversationHistory(state, conversation)
            },
        },

        autoRun: [false as boolean, { setAutoRun: (_, { autoRun }) => autoRun }],
    }),

    loaders({
        conversationHistory: [
            [] as ConversationDetail[],
            {
                loadConversationHistory: async (
                    // eslint-disable-next-line @typescript-eslint/no-unused-vars -- Used for conversation restoration
                    _?: {
                        /** If true, the current thread will not be updated with the retrieved conversation. */
                        doNotUpdateCurrentThread?: boolean
                    }
                ) => {
                    const response = await api.conversations.list()
                    return response.results
                },
            },
        ],
    }),

    selectors({
        conversation: [
            (s) => [s.conversationHistory, s.conversationId],
            (conversationHistory, conversationId) => {
                if (conversationId && !isTempId(conversationId)) {
                    return conversationHistory.find((c) => c.id === conversationId) ?? null
                }
                return null
            },
        ],

        description: [
            (s) => [s.toolDescriptions],
            (toolDescriptions): string => {
                if (toolDescriptions.length > 0) {
                    return `I'm Max. ${toolDescriptions[0]}`
                }
                return "I'm Max, here to help you build a successful product."
            },
            // It's important we use a deep equality check for inputs, because we want to avoid needless re-renders
            { equalityCheck: objectsEqual },
        ],

        toolHeadlines: [(s) => [s.tools], (tools) => tools.map((tool) => tool.introOverride?.headline).filter(Boolean)],

        toolDescriptions: [
            (s) => [s.tools],
            (tools) => tools.map((tool) => tool.introOverride?.description).filter(Boolean),
        ],

        headline: [
            (s) => [s.conversation, s.toolHeadlines],
            (conversation, toolHeadlines) => {
                if (process.env.STORYBOOK) {
                    return HEADLINES[0] // Preventing UI snapshots from being different every time
                }

                return toolHeadlines.length > 0
                    ? toolHeadlines[0]
                    : HEADLINES[
                          parseInt((conversation?.id || uuid()).split('-').at(-1) as string, 16) % HEADLINES.length
                      ]
            },
            // It's important we use a deep equality check for inputs, because we want to avoid needless re-renders
            { equalityCheck: objectsEqual },
        ],

        conversationLoading: [
            (s) => [s.conversationHistory, s.conversationHistoryLoading, s.conversationId, s.conversation],
            (conversationHistory, conversationHistoryLoading, conversationId, conversation) => {
                return (
                    !conversationHistory.length &&
                    conversationHistoryLoading &&
                    !!conversationId &&
                    !isTempId(conversationId) &&
                    !conversation
                )
            },
        ],

        threadVisible: [(s) => [s.conversationId], (conversationId) => !!conversationId],

        backButtonDisabled: [
            (s) => [s.threadVisible, s.conversationHistoryVisible],
            (threadVisible, conversationHistoryVisible) => {
                return !threadVisible && !conversationHistoryVisible
            },
        ],

        chatTitle: [
            (s) => [s.conversationId, s.conversation, s.conversationHistoryVisible],
            (conversationId, conversation, conversationHistoryVisible) => {
                if (conversationHistoryVisible) {
                    return 'Chat history'
                }

                // Existing conversation or the first generation is in progress
                if (conversation || isTempId(conversationId)) {
                    return conversation?.title ?? 'New chat'
                }

                // Conversation is loading
                if (conversationId) {
                    return null
                }

                return 'Max AI'
            },
        ],

        threadLogicKey: [
            (s) => [s.threadKeys, s.conversationId, s.tempConversationId],
            (threadKeys, conversationId, tempConversationId) => {
                if (conversationId) {
                    return threadKeys[conversationId] || conversationId
                }
                return tempConversationId
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        scrollThreadToBottom: ({ behavior }) => {
            requestAnimationFrame(() => {
                // On next frame so that the message has been rendered
                const threadEl = document.getElementsByClassName('@container/thread')[0]
                const scrollableEl = getScrollableContainer(threadEl)
                if (scrollableEl) {
                    scrollableEl.scrollTo({
                        top: threadEl.scrollHeight,
                        behavior: (behavior ?? 'smooth') as ScrollBehavior,
                    })
                }
            })
        },

        loadConversationHistorySuccess: ({ payload }) => {
            // Don't update the thread if:
            // the current chat is not a chat with ID
            // the current chat is a temp chat
            // we have explicitly marked
            // we're in an autorun conversation
            if (
                !values.conversationId ||
                values.autoRun ||
                isTempId(values.conversationId) ||
                payload?.doNotUpdateCurrentThread
            ) {
                return
            }

            const conversation = values.conversation

            // If the user has opened a conversation from a direct link, we verify that the conversation exists
            // after the history has been loaded.
            if (conversation) {
                actions.scrollThreadToBottom('instant')
                if (conversation.status === ConversationStatus.InProgress) {
                    // If the conversation is in progress, poll the conversation status.
                    actions.pollConversation(values.conversationId)
                }
            } else {
                // If the conversation is not found, retrieve once the conversation status and reset if 404.
                actions.pollConversation(values.conversationId, 0, 0)
            }
        },

        loadConversationHistoryFailure: ({ errorObject }) => {
            lemonToast.error(errorObject?.data?.detail || 'Failed to load conversation history.')
        },

        /**
         * Polls the conversation status until it's idle or reaches a max recursion depth.
         */
        pollConversation: async ({ conversationId, currentRecursionDepth, leadingTimeout }, breakpoint) => {
            if (currentRecursionDepth > 10) {
                return
            }

            if (leadingTimeout) {
                await breakpoint(leadingTimeout)
            }

            let conversation: ConversationDetail | null = null

            try {
                conversation = await api.conversations.get(conversationId)
            } catch (err: any) {
                // If conversation is not found, reset the thread completely.
                if (err.status === 404) {
                    actions.startNewConversation()
                    lemonToast.error('The chat has not been found.')
                    return
                }

                lemonToast.error(err?.data?.detail || 'Failed to load the chat.')
            }

            if (conversation && conversation.status === ConversationStatus.Idle) {
                actions.prependOrReplaceConversation(conversation)
                actions.scrollThreadToBottom('instant')
            } else {
                actions.pollConversation(conversationId, currentRecursionDepth + 1)
            }
        },

        toggleConversationHistory: () => {
            if (values.conversationHistoryVisible) {
                const threadEl = document.getElementsByClassName('@container/thread')[0]
                const scrollableEl = getScrollableContainer(threadEl)
                if (scrollableEl) {
                    scrollableEl.scrollTo({
                        top: 0,
                        behavior: 'instant' as ScrollBehavior,
                    })
                }
            } else {
                actions.scrollThreadToBottom('instant')
            }
        },

        goBack: () => {
            if (values.backToScreen === 'history' && !values.conversationHistoryVisible) {
                actions.toggleConversationHistory(true)
            } else {
                actions.startNewConversation()
            }
        },

        startNewConversation: () => {
            actions.resetContext()
            actions.focusInput()
        },
    })),

    afterMount(({ actions, values }) => {
        // If there is a prefill question from side panel state (from opening Max within the app), use it
        if (
            !values.question &&
            sidePanelStateLogic.isMounted() &&
            sidePanelStateLogic.values.selectedTab === SidePanelTab.Max &&
            sidePanelStateLogic.values.selectedTabOptions
        ) {
            const cleanedQuestion = sidePanelStateLogic.values.selectedTabOptions.replace(/^!/, '')
            actions.setQuestion(cleanedQuestion)
            if (sidePanelStateLogic.values.selectedTabOptions.startsWith('!')) {
                actions.setAutoRun(true)
            }
        }

        // Load conversation history on mount
        actions.loadConversationHistory()
    }),

    urlToAction(({ actions, values }) => ({
        /**
         * When the URL contains a conversation ID, we want to make that conversation the active one.
         */
        '*': (_, search) => {
            if (!search.chat || search.chat === values.conversationId) {
                return
            }

            actions.setConversationId(search.chat)

            if (!sidePanelStateLogic.values.sidePanelOpen && !router.values.location.pathname.includes('/max')) {
                sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max)
            }

            const conversation = values.conversationHistory.find((c) => c.id === search.chat)

            if (conversation) {
                actions.scrollThreadToBottom('instant')
            } else if (!values.conversationHistoryLoading) {
                actions.pollConversation(search.chat, 0, 0)
            }

            if (values.conversationHistoryVisible) {
                actions.toggleConversationHistory(false)
                actions.setBackScreen('history')
            }
        },
    })),

    actionToUrl(() => ({
        startNewConversation: () => {
            const { chat, ...params } = decodeParams(router.values.location.search, '?')
            return [router.values.location.pathname, params, router.values.location.hash]
        },
    })),

    permanentlyMount(), // Prevent state from being reset when Max is unmounted, especially key in the side panel
])

export function getScrollableContainer(element?: Element | null): HTMLElement | null {
    if (!element) {
        return null
    }

    const scrollableEl = element.parentElement // .Navigation3000__scene or .SidePanel3000__content

    // Check if the parent element has overflow-y-auto (for floating input case)
    if (scrollableEl && scrollableEl.classList.contains('overflow-y-auto')) {
        return scrollableEl
    }

    if (scrollableEl && !scrollableEl.classList.contains('SidePanel3000__content')) {
        // In this case we need to go up to <main>, since .Navigation3000__scene is not scrollable
        return scrollableEl.parentElement
    }
    return scrollableEl
}

export const QUESTION_SUGGESTIONS_DATA: readonly SuggestionGroup[] = [
    {
        label: 'Product analytics',
        icon: <IconGraph />,
        suggestions: [
            {
                content: 'Create a funnel of the Pirate Metrics (AARRR)',
            },
            {
                content: 'What are the most popular pages or screens?',
            },
            {
                content: 'What is the retention in the last two weeks?',
            },
            {
                content: 'What are the top referring domains?',
            },
            {
                content: 'Calculate a conversion rate for <events or actions>…',
            },
        ],
        tooltip: 'Max can generate insights from natural language and tweak existing ones.',
    },
    {
        label: 'SQL',
        icon: <IconHogQL />,
        suggestions: [
            {
                content: 'Write an SQL query to…',
            },
        ],
        url: urls.sqlEditor(),
        tooltip: 'Max can generate SQL queries for your PostHog data, both analytics and the data warehouse.',
    },
    {
        label: 'Session replay',
        icon: <IconRewindPlay />,
        suggestions: [
            {
                content: 'Find recordings for…',
            },
        ],
        url: productUrls.replay(),
        tooltip: 'Max can find session recordings for you.',
    },
    {
        label: 'SDK setup',
        icon: <IconPlug />,
        suggestions: [
            {
                content: 'How can I set up the session replay in <a framework or language>…',
            },
            {
                content: 'How can I set up the feature flags in…',
            },
            {
                content: 'How can I set up the experiments in…',
            },
            {
                content: 'How can I set up the data warehouse in…',
            },
            {
                content: 'How can I set up the error tracking in…',
            },
            {
                content: 'How can I set up the LLM Observability in…',
            },
            {
                content: 'How can I set up the product analytics in…',
            },
        ],
        tooltip: 'Max can help you set up PostHog SDKs in your stack.',
    },
    {
        label: 'Docs',
        icon: <IconBook />,
        suggestions: [
            {
                content: 'How can I create a feature flag?',
            },
            {
                content: 'Where do I watch session replays?',
            },
            {
                content: 'Help me set up an experiment',
            },
            {
                content: 'Explain autocapture',
            },
            {
                content: 'How can I capture an exception?',
            },
        ],
        tooltip: 'Max has access to PostHog docs and can help you get the most out of PostHog.',
    },
]

/**
 * Merges a new conversation into the conversation history.
 */
export function mergeConversationHistory(
    state: ConversationDetail[],
    newConversation: ConversationDetail | Conversation
): ConversationDetail[] {
    const index = state.findIndex((c) => c.id === newConversation.id)
    if (index !== -1) {
        return [...state.slice(0, index), mergeConversations(newConversation, state[index]), ...state.slice(index + 1)]
    }

    // Insert and make sure it's sorted by date
    return [mergeConversations(newConversation), ...state].sort((a, b) => {
        const dateA = a.updated_at ? dayjs(a.updated_at).valueOf() : 0
        const dateB = b.updated_at ? dayjs(b.updated_at).valueOf() : 0
        return dateB - dateA
    })
}

/**
 * Stream returns a `Conversation` object, which doesn't have a `messages` property.
 * However, when we load the conversation history, we get `ConversationDetail` objects.
 * This function merges the two types so that we can use the same logic for both.
 */
export function mergeConversations(
    newObj: Conversation | ConversationDetail,
    oldObj?: ConversationDetail
): ConversationDetail {
    if ('messages' in newObj) {
        return newObj
    }

    return {
        ...newObj,
        messages: oldObj?.messages ?? [],
    }
}

export function generateTempId(): string {
    return `new-${uuid()}`
}

export function isTempId(id?: string | null): boolean {
    return id?.startsWith('new-') ?? false
}
