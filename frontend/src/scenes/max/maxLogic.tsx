import { actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { IconBook, IconGraph, IconHogQL, IconPlug, IconRewindPlay } from '@posthog/icons'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { IconSurveys } from 'lib/lemon-ui/icons'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { objectsEqual, uuid } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { maxSettingsLogic } from 'scenes/settings/environment/maxSettingsLogic'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { actionsModel } from '~/models/actionsModel'
import { productUrls } from '~/products'
import { RootAssistantMessage } from '~/queries/schema/schema-assistant-messages'
import { Breadcrumb, Conversation, ConversationDetail, ConversationStatus, SidePanelTab } from '~/types'

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

function handleCommandString(options: string, actions: maxLogicType['actions']): void {
    if (options.startsWith('!')) {
        actions.setAutoRun(true)
    }
    const cleanedQuestion = options.replace(/^!/, '')
    if (cleanedQuestion.trim() !== '') {
        actions.setQuestion(cleanedQuestion)
    }
}

export const maxLogic = kea<maxLogicType>([
    path(['scenes', 'max', 'maxLogic']),
    props({} as { tabId: string | 'sidepanel' }),
    tabAwareScene(),

    connect(() => ({
        values: [
            router,
            ['searchParams'],
            maxGlobalLogic,
            ['dataProcessingAccepted', 'tools', 'toolSuggestions', 'conversationHistory', 'conversationHistoryLoading'],
            maxSettingsLogic,
            ['coreMemory'],
            // Actions are lazy-loaded. In order to display their names in the UI, we're loading them here.
            actionsModel({ params: 'include_count=1' }),
            ['actions'],
        ],
        actions: [
            maxContextLogic,
            ['resetContext'],
            maxGlobalLogic,
            ['loadConversationHistory', 'prependOrReplaceConversation', 'loadConversationHistorySuccess'],
        ],
    })),

    actions({
        setQuestion: (question: string) => ({ question }), // update the form input
        askMax: (prompt: string | null) => ({ prompt }), // used by maxThreadLogic to start a conversation
        scrollThreadToBottom: (behavior?: 'instant' | 'smooth') => ({ behavior }),
        openConversation: (conversationId: string) => ({ conversationId }),
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
        incrActiveStreamingThreads: true,
        decrActiveStreamingThreads: true,
        setAutoRun: (autoRun: boolean) => ({ autoRun }),
    }),

    reducers({
        activeStreamingThreads: [
            0,
            {
                incrActiveStreamingThreads: (state) => state + 1,
                decrActiveStreamingThreads: (state) => Math.max(state - 1, 0),
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

        // The frontend-generated UUID for new conversations
        frontendConversationId: [
            (() => uuid()) as any as string,
            {
                startNewConversation: () => uuid(),
            },
        ],

        conversationHistoryVisible: [
            false,
            {
                toggleConversationHistory: (state, { visible }) => visible ?? !state,
                startNewConversation: () => false,
                setConversationId: () => false,
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

        autoRun: [false as boolean, { setAutoRun: (_, { autoRun }) => autoRun }],
    }),

    selectors({
        tabId: [() => [(_, props) => props?.tabId || ''], (tabId) => tabId],
        conversation: [
            (s) => [s.conversationHistory, s.conversationId],
            (conversationHistory, conversationId) => {
                if (conversationId) {
                    return conversationHistory.find((c) => c.id === conversationId) ?? null
                }
                return null
            },
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
                return !conversationHistory.length && conversationHistoryLoading && !!conversationId && !conversation
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
                if (conversationId || conversation) {
                    return conversation?.title ?? 'New chat'
                }

                return null
            },
        ],

        threadLogicKey: [
            (s) => [s.conversationId, s.frontendConversationId],
            (conversationId, frontendConversationId) => {
                if (conversationId) {
                    return conversationId
                }
                return frontendConversationId
            },
        ],

        threadLogicProps: [
            (s) => [s.tabId, s.conversation, s.threadLogicKey],
            (tabId, conversation, threadLogicKey) => ({
                tabId,
                conversationId: threadLogicKey,
                conversation,
            }),
        ],

        breadcrumbs: [
            (s) => [s.conversationId, s.chatTitle, s.conversationHistoryVisible, s.searchParams],
            (conversationId, chatTitle, conversationHistoryVisible, searchParams): Breadcrumb[] => {
                return [
                    {
                        key: Scene.Max,
                        name: 'AI',
                        path: urls.max(),
                        iconType: 'chat',
                    },
                    ...(conversationHistoryVisible || searchParams.from === 'history'
                        ? [
                              {
                                  key: Scene.Max,
                                  name: 'Chat history',
                                  path: urls.maxHistory(),
                                  iconType: 'chat' as const,
                              },
                          ]
                        : []),
                    ...(!conversationHistoryVisible && conversationId
                        ? [
                              {
                                  key: Scene.Max,
                                  name: chatTitle || 'Chat',
                                  path: urls.max(conversationId),
                                  iconType: 'chat' as const,
                              },
                          ]
                        : []),
                ]
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        // Listen for when the side panel state changes and check for initial prompt
        [sidePanelStateLogic.actionTypes.openSidePanel]: ({ tab, options }) => {
            if (tab === SidePanelTab.Max && options && typeof options === 'string') {
                handleCommandString(options, actions)
            }
        },
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
            // - the current chat is not a chat with ID
            // - the current chat is a temp chat
            // - we have explicitly marked we're in an autorun conversation
            if (!values.conversationId || values.autoRun || payload?.doNotUpdateCurrentThread) {
                return
            }

            const conversation = values.conversation

            // If the user has opened a conversation from a direct link, we verify that the conversation exists
            // after the history has been loaded.
            if (conversation) {
                actions.scrollThreadToBottom('instant')
            } else {
                // If the conversation is not found, retrieve once the conversation status and reset if 404.
                actions.pollConversation(values.conversationId, 0, 0)
            }
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
                if (err.status === 404) {
                    // If conversation is not found, do nothing. In the normal case a NotFound will be shown.
                    // There's also a not-quite-normal case of a race condition: when loadConversationHistory succeeds WHILE
                    // a message is being generated (e.g. because user messaged Max before initial load of conversations completed).
                    // In this case, we especially want to do nothing, so that the normal course of generation isn't interrupted.
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

        openConversation({ conversationId }) {
            actions.setConversationId(conversationId)

            const conversation = values.conversationHistory.find((c) => c.id === conversationId)

            if (conversation) {
                actions.scrollThreadToBottom('instant')
            } else if (!values.conversationHistoryLoading) {
                actions.pollConversation(conversationId, 0, 200)
            }

            if (values.conversationHistoryVisible) {
                actions.toggleConversationHistory(false)
                actions.setBackScreen('history')
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
            sidePanelStateLogic.values.selectedTabOptions &&
            typeof sidePanelStateLogic.values.selectedTabOptions === 'string'
        ) {
            handleCommandString(sidePanelStateLogic.values.selectedTabOptions, actions)
        }

        // Load conversation history on mount
        actions.loadConversationHistory()
    }),

    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.maxHistory()]: () => {
            if (!values.conversationHistoryVisible) {
                actions.toggleConversationHistory()
            }
        },
        [urls.max()]: (_, search) => {
            if (search.ask && !search.chat && !values.question) {
                window.setTimeout(() => {
                    // ensure maxThreadLogic is mounted
                    actions.askMax(search.ask)
                }, 100)
                return
            }

            if (!search.chat && values.conversationId) {
                actions.startNewConversation()
            } else if (search.chat && search.chat !== values.conversationId) {
                actions.openConversation(search.chat)
            } else if (values.conversationHistoryVisible) {
                actions.toggleConversationHistory()
            }
        },
    })),

    tabAwareActionToUrl(({ values }) => ({
        toggleConversationHistory: () => {
            if (values.conversationHistoryVisible) {
                return [urls.maxHistory(), {}, router.values.location.hash]
            } else if (values.conversationId) {
                return [urls.max(values.conversationId), {}, router.values.location.hash]
            }
            return [urls.max(), {}, router.values.location.hash]
        },
        startNewConversation: () => {
            return [urls.max(), {}, router.values.location.hash]
        },
        setConversationId: ({ conversationId }) => {
            // Only set the URL parameter if this is a new conversation (using frontendConversationId)
            if (conversationId && conversationId === values.frontendConversationId) {
                return [urls.max(conversationId), {}, router.values.location.hash, { replace: true }]
            }
            // Return undefined to not update URL for existing conversations
            return undefined
        },
    })),
])

export function getScrollableContainer(element?: Element | null): HTMLElement | null {
    if (!element) {
        return null
    }
    const scrollableEl = element.parentElement // .Navigation3000__scene or .SidePanel3000__content
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
        tooltip: 'PostHog AI can generate insights from natural language and tweak existing ones.',
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
        tooltip: 'PostHog AI can generate SQL queries for your PostHog data, both analytics and the data warehouse.',
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
        tooltip: 'PostHog AI can find session recordings for you.',
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
                content: 'How can I set up the LLM analytics in…',
            },
            {
                content: 'How can I set up the product analytics in…',
            },
        ],
        tooltip: 'PostHog AI can help you set up PostHog SDKs in your stack.',
    },
    {
        label: 'Surveys',
        icon: <IconSurveys />,
        suggestions: [
            {
                content: 'Create a survey to collect NPS responses from users',
            },
            {
                content: 'Create a survey to CSAT responses from users',
            },
            {
                content: 'Create a survey to measure product market fit',
            },
            {
                content: 'Analyze survey responses to prioritize key features our users are interested in',
            },
        ],
        url: urls.surveys(),
        tooltip: 'PostHog AI can help you create surveys to collect feedback from your users.',
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
        tooltip: 'PostHog AI has access to PostHog docs and can help you get the most out of PostHog.',
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
