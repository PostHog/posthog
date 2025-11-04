import {
    CONVERSATION_ID,
    chatResponseChunk,
    chatResponseWithEventContext,
    failureChunk,
    formChunk,
    generationFailureChunk,
    humanMessage,
    longResponseChunk,
    sqlQueryResponseChunk,
} from './__mocks__/chatResponse.mocks'
import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { Meta, StoryFn } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { twMerge } from 'tailwind-merge'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import {
    AssistantMessage,
    AssistantMessageType,
    AssistantToolCallMessage,
    MultiVisualizationMessage,
    NotebookUpdateMessage,
} from '~/queries/schema/schema-assistant-messages'
import { FunnelsQuery, TrendsQuery } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, InsightShortId, PropertyFilterType, PropertyOperator } from '~/types'

import { MaxInstance, MaxInstanceProps } from './Max'
import conversationList from './__mocks__/conversationList.json'
import { ToolRegistration } from './max-constants'
import { maxContextLogic } from './maxContextLogic'
import { maxGlobalLogic } from './maxGlobalLogic'
import { QUESTION_SUGGESTIONS_DATA, maxLogic } from './maxLogic'
import { maxThreadLogic } from './maxThreadLogic'

const meta: Meta = {
    title: 'Scenes-App/PostHog AI',
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/conversations/': (_, res, ctx) => res(ctx.text(chatResponseChunk)),
            },
            get: {
                '/api/organizations/@current/': () => [
                    200,
                    {
                        ...MOCK_DEFAULT_ORGANIZATION,
                        is_ai_data_processing_approved: true,
                    },
                ],
                '/api/environments/:team_id/conversations/': () => [200, conversationList],
                [`/api/environments/:team_id/conversations/${CONVERSATION_ID}/`]: () => [
                    200,
                    {
                        id: CONVERSATION_ID,
                        status: 'idle',
                        title: 'Test Conversation',
                        created_at: '2025-04-29T17:44:21.654307Z',
                        updated_at: '2025-04-29T17:44:29.184791Z',
                        messages: [],
                    },
                ],
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
        featureFlags: [FEATURE_FLAGS.ARTIFICIAL_HOG],
    },
}
export default meta

const Template = ({ className, ...props }: Omit<MaxInstanceProps, 'tabId'> & { className?: string }): JSX.Element => {
    return (
        <div className={twMerge('relative flex flex-col h-fit', className)}>
            <MaxInstance tabId="storybook" {...props} />
        </div>
    )
}

export const Welcome: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/organizations/@current/': () => [
                200,
                {
                    ...MOCK_DEFAULT_ORGANIZATION,
                    // We override data processing opt-in to false, so that we see the welcome screen as a first-time user would
                    is_ai_data_processing_approved: false,
                },
            ],
        },
    })

    return <Template />
}
Welcome.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const WelcomeFeaturePreviewAutoEnrolled: StoryFn = () => {
    return <Template />
}
WelcomeFeaturePreviewAutoEnrolled.parameters = {
    featureFlags: [],
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const Thread: StoryFn = () => {
    const { setConversationId } = useActions(maxLogic({ tabId: 'storybook' }))
    const { askMax } = useActions(
        maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null, tabId: 'storybook' })
    )
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    useEffect(() => {
        if (dataProcessingAccepted) {
            setTimeout(() => {
                setConversationId(CONVERSATION_ID)
                askMax(humanMessage.content)
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}

export const EmptyThreadLoading: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/conversations/': (_req, _res, ctx) => [ctx.delay('infinite')],
        },
    })

    const { setConversationId } = useActions(maxLogic({ tabId: 'storybook' }))
    const threadLogic = maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null, tabId: 'storybook' })
    const { askMax } = useActions(threadLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    useEffect(() => {
        if (dataProcessingAccepted) {
            setTimeout(() => {
                setConversationId(CONVERSATION_ID)
                askMax(humanMessage.content)
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}
EmptyThreadLoading.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const GenerationFailureThread: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/conversations/': (_, res, ctx) => res(ctx.text(generationFailureChunk)),
        },
    })

    const { setConversationId } = useActions(maxLogic({ tabId: 'storybook' }))
    const threadLogic = maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null, tabId: 'storybook' })
    const { askMax, setMessageStatus } = useActions(threadLogic)
    const { threadRaw, threadLoading } = useValues(threadLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    useEffect(() => {
        if (dataProcessingAccepted) {
            setTimeout(() => {
                setConversationId(CONVERSATION_ID)
                askMax(humanMessage.content)
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    useEffect(() => {
        if (threadRaw.length === 2 && !threadLoading) {
            setMessageStatus(1, 'error')
        }
    }, [threadRaw.length, threadLoading, setMessageStatus])

    if (!dataProcessingAccepted) {
        return <></>
    }
    return <Template />
}

export const ThreadWithFailedGeneration: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/conversations/': (_, res, ctx) => res(ctx.text(failureChunk)),
        },
    })

    const { setConversationId } = useActions(maxLogic({ tabId: 'storybook' }))
    const threadLogic = maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null, tabId: 'storybook' })
    const { askMax } = useActions(threadLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    useEffect(() => {
        if (dataProcessingAccepted) {
            setTimeout(() => {
                setConversationId(CONVERSATION_ID)
                askMax(humanMessage.content)
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}

export const ThreadWithRateLimit: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/conversations/': (_, res, ctx) =>
                // Retry-After header is present so we should be showing its value in the UI
                res(ctx.text(chatResponseChunk), ctx.set({ 'Retry-After': '3899' }), ctx.status(429)),
        },
    })

    const { setConversationId } = useActions(maxLogic({ tabId: 'storybook' }))
    const threadLogic = maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null, tabId: 'storybook' })
    const { askMax } = useActions(threadLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    useEffect(() => {
        if (dataProcessingAccepted) {
            setTimeout(() => {
                setConversationId(CONVERSATION_ID)
                askMax(humanMessage.content)
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}

export const ThreadWithRateLimitNoRetryAfter: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/conversations/': (_, res, ctx) =>
                // Testing rate limit error when the Retry-After header is MISSING
                res(ctx.text(chatResponseChunk), ctx.status(429)),
        },
    })

    const { setConversationId } = useActions(maxLogic({ tabId: 'storybook' }))
    const threadLogic = maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null, tabId: 'storybook' })
    const { askMax } = useActions(threadLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    useEffect(() => {
        if (dataProcessingAccepted) {
            setTimeout(() => {
                setConversationId(CONVERSATION_ID)
                askMax(humanMessage.content)
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}

export const ThreadWithForm: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/conversations/': (_, res, ctx) => res(ctx.text(formChunk)),
        },
    })

    const { setConversationId } = useActions(maxLogic({ tabId: 'storybook' }))
    const threadLogic = maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null, tabId: 'storybook' })
    const { askMax } = useActions(threadLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    useEffect(() => {
        if (dataProcessingAccepted) {
            setTimeout(() => {
                setConversationId(CONVERSATION_ID)
                askMax(humanMessage.content)
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}

export const ThreadWithConversationLoading: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/conversations/': (_req, _res, ctx) => [ctx.delay('infinite')],
        },
    })

    const { setConversationId } = useActions(maxLogic({ tabId: 'storybook' }))

    useEffect(() => {
        setConversationId(CONVERSATION_ID)
    }, [setConversationId])

    return <Template />
}
ThreadWithConversationLoading.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const ThreadWithEmptyConversation: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/conversations/': () => [200, conversationList],
        },
    })

    const { setConversationId } = useActions(maxLogic({ tabId: 'storybook' }))

    useEffect(() => {
        setConversationId('empty')
    }, [setConversationId])

    return <Template />
}

export const ThreadWithInProgressConversation: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/conversations/': () => [200, conversationList],
            '/api/environments/:team_id/conversations/in_progress/': (_req, _res, ctx) => [ctx.delay('infinite')],
        },
    })

    const { setConversationId } = useActions(maxLogic({ tabId: 'storybook' }))

    useEffect(() => {
        setConversationId('in_progress')
    }, [setConversationId])

    return <Template sidePanel />
}
ThreadWithInProgressConversation.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const WelcomeWithLatestConversations: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/conversations/': () => [200, conversationList],
        },
    })

    return <Template sidePanel />
}
WelcomeWithLatestConversations.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const ChatHistory: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/conversations/': () => [200, conversationList],
        },
    })

    const { toggleConversationHistory } = useActions(maxLogic({ tabId: 'storybook' }))

    useEffect(() => {
        toggleConversationHistory(true)
    }, [toggleConversationHistory])

    return <Template sidePanel />
}
ChatHistory.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const ChatHistoryEmpty: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/conversations/': () => [400],
        },
    })

    const { toggleConversationHistory } = useActions(maxLogic({ tabId: 'storybook' }))

    useEffect(() => {
        toggleConversationHistory(true)
    }, [toggleConversationHistory])

    return <Template sidePanel />
}
ChatHistoryEmpty.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const ChatHistoryLoading: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/conversations/': (_req, _res, ctx) => [ctx.delay('infinite')],
        },
    })

    const { toggleConversationHistory } = useActions(maxLogic({ tabId: 'storybook' }))

    useEffect(() => {
        toggleConversationHistory(true)
    }, [toggleConversationHistory])

    return <Template sidePanel />
}
ChatHistoryLoading.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const ThreadWithOpenedSuggestionsMobile: StoryFn = () => {
    const { setActiveGroup } = useActions(maxLogic({ tabId: 'storybook' }))

    useEffect(() => {
        // The largest group is the set up group
        if (QUESTION_SUGGESTIONS_DATA[3]) {
            setActiveGroup(QUESTION_SUGGESTIONS_DATA[3])
        }
    }, [setActiveGroup])

    return <Template sidePanel />
}
ThreadWithOpenedSuggestionsMobile.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
    viewport: {
        defaultViewport: 'mobile2',
    },
}

export const ThreadWithOpenedSuggestions: StoryFn = () => {
    const { setActiveGroup } = useActions(maxLogic({ tabId: 'storybook' }))

    useEffect(() => {
        // The largest group is the set up group
        if (QUESTION_SUGGESTIONS_DATA[3]) {
            setActiveGroup(QUESTION_SUGGESTIONS_DATA[3])
        }
    }, [setActiveGroup])

    return <Template sidePanel />
}
ThreadWithOpenedSuggestions.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const ThreadWithMultipleContextObjects: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/conversations/': () => [200, conversationList],
        },
    })

    const { addOrUpdateContextInsight } = useActions(maxContextLogic)

    useEffect(() => {
        // Add multiple context insights
        addOrUpdateContextInsight({
            short_id: 'insight-1' as InsightShortId,
            name: 'Weekly Active Users',
            description: 'Track weekly active users over time',
            query: {
                kind: 'TrendsQuery',
                series: [{ event: '$pageview' }],
            } as TrendsQuery,
        })

        addOrUpdateContextInsight({
            short_id: 'insight-2' as InsightShortId,
            name: 'Conversion Funnel',
            description: 'User signup to activation funnel',
            query: {
                kind: 'FunnelsQuery',
                series: [{ event: 'sign up' }, { event: 'first action' }],
            } as FunnelsQuery,
        })
    }, [addOrUpdateContextInsight])

    return <Template sidePanel />
}
ThreadWithMultipleContextObjects.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const ThreadScrollsToBottomOnNewMessages: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/conversations/': () => [200, conversationList],
        },
        post: {
            '/api/environments/:team_id/conversations/': (_, res, ctx) =>
                res(ctx.delay(100), ctx.text(longResponseChunk)),
        },
    })

    const { conversation } = useValues(maxLogic({ tabId: 'storybook' }))
    const { setConversationId } = useActions(maxLogic({ tabId: 'storybook' }))
    const logic = maxThreadLogic({ conversationId: 'poem', conversation, tabId: 'storybook' })
    const { threadRaw } = useValues(logic)
    const { askMax } = useActions(logic)

    useEffect(() => {
        setConversationId('poem')
    }, [setConversationId])

    const messagesSet = threadRaw.length > 0
    useEffect(() => {
        if (messagesSet) {
            askMax('This message must be on the top of the container')
        }
    }, [messagesSet, askMax])

    return (
        <div className="h-fit max-h-screen overflow-y-auto SidePanel3000__content">
            <Template />
        </div>
    )
}
ThreadScrollsToBottomOnNewMessages.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const ChatWithUIContext: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/conversations/': (_, res, ctx) => res(ctx.text(chatResponseWithEventContext)),
        },
        get: {
            '/api/environments/:team_id/conversations/': () => [200, conversationList],
            [`/api/environments/:team_id/conversations/${CONVERSATION_ID}/`]: () => [
                200,
                {
                    id: CONVERSATION_ID,
                    status: 'idle',
                    title: 'Event Context Test',
                    created_at: '2025-04-29T17:44:21.654307Z',
                    updated_at: '2025-04-29T17:44:29.184791Z',
                    messages: [],
                },
            ],
        },
    })

    const { contextEvents } = useValues(maxContextLogic)
    const { addOrUpdateContextEvent } = useActions(maxContextLogic)
    const { setConversationId } = useActions(maxLogic({ tabId: 'storybook' }))
    const threadLogic = maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null, tabId: 'storybook' })
    const { askMax } = useActions(threadLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    useEffect(() => {
        // Add an event to the context
        if (dataProcessingAccepted) {
            addOrUpdateContextEvent({
                id: 'test-event-1',
                name: '$pageview',
                description: 'Page view event',
                tags: [],
            })
        }
    }, [addOrUpdateContextEvent, dataProcessingAccepted])

    useEffect(() => {
        // After event is added, start a new conversation
        if (dataProcessingAccepted && contextEvents.length > 0) {
            setTimeout(() => {
                // This simulates starting a new chat which changes the URL
                setConversationId(CONVERSATION_ID)
                askMax('Tell me about the $pageview event')
            }, 100)
        }
    }, [contextEvents.length, setConversationId, askMax, dataProcessingAccepted])

    useEffect(() => {
        // Verify context is still present after conversation starts
        if (contextEvents.length > 0) {
            console.info('Event context preserved:', contextEvents)
        }
    }, [contextEvents])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}
ChatWithUIContext.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const MaxInstanceWithContextualTools: StoryFn = () => {
    const { registerTool } = useActions(maxGlobalLogic)

    useEffect(() => {
        // Register various contextual tools for MaxInstance
        registerTool({
            identifier: 'query_insights' as ToolRegistration['identifier'],
            name: 'Query insights',
            description: 'Max can query insights and their properties',
            context: {
                available_insights: ['pageview_trends', 'user_retention', 'conversion_rates'],
                active_filters: { date_from: '-7d', properties: [{ key: 'browser', value: 'Chrome' }] },
                user_permissions: ['read_insights', 'create_insights'],
            },
            callback: (toolOutput) => {
                console.info('Querying insights:', toolOutput)
            },
        })

        registerTool({
            identifier: 'manage_cohorts' as ToolRegistration['identifier'],
            name: 'Manage cohorts',
            description: 'Max can manage cohorts and their properties',
            context: {
                existing_cohorts: [
                    { id: 1, name: 'Power Users', size: 1250 },
                    { id: 2, name: 'New Signups', size: 3400 },
                ],
                cohort_types: ['behavioral', 'demographic', 'custom'],
            },
            callback: (toolOutput) => {
                console.info('Managing cohorts:', toolOutput)
            },
        })

        registerTool({
            identifier: 'feature_flags' as ToolRegistration['identifier'],
            name: 'Feature flags',
            description: 'Max can manage feature flags and their properties',
            context: {
                active_flags: ['new-dashboard', 'beta-feature', 'experiment-checkout'],
                flag_stats: { total: 15, active: 8, inactive: 7 },
                rollout_percentages: { 'new-dashboard': 25, 'beta-feature': 50 },
            },
            callback: (toolOutput) => {
                console.info('Feature flag action:', toolOutput)
            },
        })
    }, [registerTool])

    return <Template />
}
MaxInstanceWithContextualTools.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const NotebookUpdateComponent: StoryFn = () => {
    const notebookMessage: NotebookUpdateMessage = {
        type: AssistantMessageType.Notebook,
        notebook_id: 'nb_123456',
        content: {
            type: 'doc',
            content: [
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'text',
                            text: 'Analysis notebook has been updated with new insights',
                        },
                    ],
                },
            ],
        },
        id: 'notebook-update-message',
    }

    useStorybookMocks({
        post: {
            '/api/environments/:team_id/conversations/': (_, res, ctx) =>
                res(
                    ctx.text(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
                            'event: message',
                            `data: ${JSON.stringify({ ...humanMessage, content: 'Update my analysis notebook' })}`,
                            'event: message',
                            `data: ${JSON.stringify(notebookMessage)}`,
                        ])
                    )
                ),
        },
    })

    const { setConversationId } = useActions(maxLogic({ tabId: 'storybook' }))
    const threadLogic = maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null, tabId: 'storybook' })
    const { askMax } = useActions(threadLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    useEffect(() => {
        if (dataProcessingAccepted) {
            setTimeout(() => {
                setConversationId(CONVERSATION_ID)
                askMax('Update my analysis notebook')
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}

export const PlanningComponent: StoryFn = () => {
    // Planning is now derived from AssistantMessage with todo_write tool call
    const planningMessage: AssistantMessage = {
        type: AssistantMessageType.Assistant,
        content: "I'll create a comprehensive analysis plan for you.",
        id: 'planning-msg-1',
        tool_calls: [
            {
                id: 'todo_1',
                name: 'todo_write',
                type: 'tool_call',
                args: {
                    todos: [
                        {
                            content: 'Analyze user engagement metrics',
                            status: 'completed',
                            activeForm: 'Analyzing user engagement metrics',
                        },
                        {
                            content: 'Create conversion funnel visualization',
                            status: 'completed',
                            activeForm: 'Creating conversion funnel visualization',
                        },
                        {
                            content: 'Generate retention cohort analysis',
                            status: 'in_progress',
                            activeForm: 'Generating retention cohort analysis',
                        },
                        {
                            content: 'Compile comprehensive report',
                            status: 'pending',
                            activeForm: 'Compiling comprehensive report',
                        },
                        {
                            content: 'Export data to dashboard',
                            status: 'pending',
                            activeForm: 'Exporting data to dashboard',
                        },
                    ],
                },
            },
        ],
    }

    useStorybookMocks({
        post: {
            '/api/environments/:team_id/conversations/': (_, res, ctx) =>
                res(
                    ctx.text(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
                            'event: message',
                            `data: ${JSON.stringify({
                                ...humanMessage,
                                content: 'Create a comprehensive analysis plan',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(planningMessage)}`,
                        ])
                    )
                ),
        },
    })

    const { setConversationId } = useActions(maxLogic({ tabId: 'storybook' }))
    const threadLogic = maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null, tabId: 'storybook' })
    const { askMax } = useActions(threadLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    useEffect(() => {
        if (dataProcessingAccepted) {
            setTimeout(() => {
                setConversationId(CONVERSATION_ID)
                askMax('Create a comprehensive analysis plan')
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}

export const ReasoningComponent: StoryFn = () => {
    // Reasoning is now derived from AssistantMessage with meta.thinking
    const reasoningMessage: AssistantMessage = {
        type: AssistantMessageType.Assistant,
        content: '',
        id: 'reasoning-msg-1',
        meta: {
            thinking: [
                {
                    type: 'thinking',
                    thinking: '*Analyzing user behavior patterns...*',
                },
            ],
        },
    }

    useStorybookMocks({
        post: {
            '/api/environments/:team_id/conversations/': (_, res, ctx) =>
                res(
                    ctx.text(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
                            'event: message',
                            `data: ${JSON.stringify({ ...humanMessage, content: 'Analyze user engagement' })}`,
                            'event: message',
                            `data: ${JSON.stringify(reasoningMessage)}`,
                        ])
                    )
                ),
        },
    })

    const { setConversationId } = useActions(maxLogic({ tabId: 'storybook' }))
    const threadLogic = maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null, tabId: 'storybook' })
    const { askMax } = useActions(threadLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    useEffect(() => {
        if (dataProcessingAccepted) {
            setTimeout(() => {
                setConversationId(CONVERSATION_ID)
                askMax('Analyze user engagement')
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}

export const TaskExecutionComponent: StoryFn = () => {
    // Task execution is now derived from AssistantMessage with regular tool calls
    const taskExecutionMessage: AssistantMessage = {
        type: AssistantMessageType.Assistant,
        content: 'Executing analysis tasks...',
        id: 'task-exec-msg-1',
        tool_calls: [
            {
                id: 'task_1',
                name: 'create_and_query_insight',
                type: 'tool_call',
                args: {},
            },
            {
                id: 'task_2',
                name: 'create_and_query_insight',
                type: 'tool_call',
                args: {
                    commentary: 'Identifying peak usage times and user segments',
                },
            },
            {
                id: 'task_3',
                name: 'search',
                type: 'tool_call',
                args: {
                    kind: 'insights',
                },
            },
            {
                id: 'task_4',
                name: 'search',
                type: 'tool_call',
                args: {
                    kind: 'docs',
                },
            },
            {
                id: 'task_5',
                name: 'create_and_query_insight',
                type: 'tool_call',
                args: {},
            },
        ],
        meta: {
            thinking: [
                {
                    thinking: 'Analyzing user engagement metrics...',
                },
            ],
        },
    }

    // Tool call completion messages for the first two tasks
    const toolCallCompletion1 = {
        type: AssistantMessageType.ToolCall,
        tool_call_id: 'task_1',
        content: 'Successfully loaded user data for the last 30 days',
        id: 'tool-completion-1',
    }

    const toolCallCompletion2 = {
        type: AssistantMessageType.ToolCall,
        tool_call_id: 'task_2',
        content: 'Engagement pattern analysis completed',
        id: 'tool-completion-2',
    }

    const updateMessages = [
        {
            tool_call_id: 'task_3',
            content: 'Fetching last 30 days of user activity',
            id: 'task-exec-msg-1-1',
        },
        {
            tool_call_id: 'task_3',
            content: 'Data loaded successfully',
            id: 'task-exec-msg-1-1',
        },
        {
            tool_call_id: 'task_4',
            content: 'Processing funnel metrics across key paths',
            id: 'task-exec-msg-1-1',
        },
        {
            tool_call_id: 'task_5',
            content: 'Exploring data...',
            id: 'task-exec-msg-1-1',
        },
    ]

    useStorybookMocks({
        post: {
            '/api/environments/:team_id/conversations/': (_, res, ctx) =>
                res(
                    ctx.text(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: 'in_progress' })}`,
                            'event: message',
                            `data: ${JSON.stringify({ ...humanMessage, content: 'Execute analysis tasks' })}`,
                            'event: message',
                            `data: ${JSON.stringify(taskExecutionMessage)}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallCompletion1)}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallCompletion2)}`,
                            'event: update',
                            `data: ${JSON.stringify(updateMessages[0])}`,
                            'event: update',
                            `data: ${JSON.stringify(updateMessages[1])}`,
                            'event: update',
                            `data: ${JSON.stringify(updateMessages[2])}`,
                            'event: update',
                            `data: ${JSON.stringify(updateMessages[3])}`,
                        ])
                    )
                ),
        },
        get: {
            '/api/environments/:team_id/conversations/in_progress/': (_req, _res, ctx) => [ctx.delay('infinite')],
        },
    })

    const { setConversationId } = useActions(maxLogic({ tabId: 'storybook' }))
    const threadLogic: ReturnType<typeof maxThreadLogic> = maxThreadLogic({
        conversationId: 'in_progress',
        conversation: null,
        tabId: 'storybook',
    })
    const { askMax } = useActions(threadLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    useEffect(() => {
        if (dataProcessingAccepted) {
            setTimeout(() => {
                askMax('Execute analysis tasks')
                setConversationId('in_progress')
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}
TaskExecutionComponent.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const TaskExecutionWithFailure: StoryFn = () => {
    // Task execution with failure - tool calls with failed status
    const taskExecutionMessage: AssistantMessage = {
        type: AssistantMessageType.Assistant,
        content: 'Executing analysis with some failures...',
        id: 'task-exec-fail-msg-1',
        tool_calls: [
            {
                id: 'task_1',
                name: 'search',
                type: 'tool_call',
                args: {
                    kind: 'insights',
                },
            },
            {
                id: 'task_2',
                name: 'search',
                type: 'tool_call',
                args: {
                    kind: 'insights',
                },
            },
            {
                id: 'task_3',
                name: 'create_and_query_insight',
                type: 'tool_call',
                args: {},
            },
            {
                id: 'task_4',
                name: 'create_and_query_insight',
                type: 'tool_call',
                args: {},
            },
            {
                id: 'task_5',
                name: 'create_and_query_insight',
                type: 'tool_call',
                args: {},
            },
        ],
    }

    // Tool call completion messages - task 1 and 2 complete, task 3 fails
    const toolCallCompletion1 = {
        type: AssistantMessageType.ToolCall,
        tool_call_id: 'task_1',
        content: 'Successfully loaded user data',
        id: 'tool-completion-fail-1',
    }

    const toolCallCompletion2 = {
        type: AssistantMessageType.ToolCall,
        tool_call_id: 'task_2',
        content: 'Engagement patterns analyzed',
        id: 'tool-completion-fail-2',
    }

    const toolCallCompletion3 = {
        type: AssistantMessageType.ToolCall,
        tool_call_id: 'task_3',
        content: 'Failed to calculate conversion rates due to insufficient data',
        id: 'tool-completion-fail-3',
    }

    useStorybookMocks({
        post: {
            '/api/environments/:team_id/conversations/': (_, res, ctx) =>
                res(
                    ctx.text(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
                            'event: message',
                            `data: ${JSON.stringify({
                                ...humanMessage,
                                content: 'Execute analysis with some failures',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(taskExecutionMessage)}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallCompletion1)}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallCompletion2)}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallCompletion3)}`,
                        ])
                    )
                ),
        },
    })

    const { setConversationId } = useActions(maxLogic({ tabId: 'storybook' }))
    const threadLogic = maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null, tabId: 'storybook' })
    const { askMax } = useActions(threadLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    useEffect(() => {
        if (dataProcessingAccepted) {
            setTimeout(() => {
                setConversationId(CONVERSATION_ID)
                askMax('Execute analysis with some failures')
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}

export const MultiVisualizationInThread: StoryFn = () => {
    // Mock the queries endpoint to return dummy data
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/query/': () => [
                200,
                {
                    results: [[100, 120, 130, 140, 150]],
                    columns: ['count'],
                    types: ['integer'],
                    hogql: 'SELECT count() FROM events',
                },
            ],
            '/api/environments/:team_id/conversations/': (_, res, ctx) => {
                const humanMsg = {
                    type: AssistantMessageType.Human,
                    content: 'Analyze our product metrics comprehensively',
                    id: 'human-multi-viz',
                }

                const multiVizMessage: MultiVisualizationMessage = {
                    type: AssistantMessageType.MultiVisualization,
                    id: 'multi-viz-1',
                    visualizations: [
                        {
                            query: 'Daily Active Users',
                            plan: 'Track user engagement over the past 30 days',
                            answer: {
                                kind: 'TrendsQuery',
                                series: [{ event: '$pageview', name: 'Pageviews' }],
                                dateRange: { date_from: '-30d' },
                            } as any,
                        },
                        {
                            query: 'User Conversion Funnel',
                            plan: 'Analyze conversion from signup to purchase',
                            answer: {
                                kind: 'FunnelsQuery',
                                series: [
                                    { event: 'user signed up' },
                                    { event: 'viewed product' },
                                    { event: 'completed purchase' },
                                ],
                            } as any,
                        },
                        {
                            query: 'Feature Adoption',
                            plan: 'Measure feature usage rates',
                            answer: {
                                kind: 'TrendsQuery',
                                series: [{ event: 'feature_used', name: 'Feature Usage' }],
                                breakdownFilter: { breakdown: 'feature_name', breakdown_type: 'event' },
                            } as any,
                        },
                    ],
                    commentary: `I've analyzed your product metrics across three key dimensions:

1. **User Engagement**: Daily active users show a positive trend with 25% growth
2. **Conversion Funnel**: 40% drop-off at payment step needs attention
3. **Feature Adoption**: New dashboard feature has 65% adoption rate

### Recommendations
- Optimize the payment flow to reduce friction
- Continue current engagement strategies
- Apply dashboard rollout strategy to future features`,
                }

                return res(
                    ctx.text(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
                            'event: message',
                            `data: ${JSON.stringify({
                                ...humanMsg,
                                content: 'Analyze our product metrics comprehensively',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(multiVizMessage)}`,
                        ])
                    )
                )
            },
        },
    })

    const { setConversationId } = useActions(maxLogic({ tabId: 'storybook' }))
    const threadLogic = maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null, tabId: 'storybook' })
    const { askMax } = useActions(threadLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    useEffect(() => {
        if (dataProcessingAccepted) {
            setTimeout(() => {
                setConversationId(CONVERSATION_ID)
                askMax('Analyze our product metrics comprehensively')
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}

export const ThreadWithSQLQueryOverflow: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/conversations/': (_, res, ctx) => res(ctx.text(sqlQueryResponseChunk)),
        },
    })

    const { setConversationId } = useActions(maxLogic({ tabId: 'storybook' }))
    const threadLogic = maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null, tabId: 'storybook' })
    const { askMax } = useActions(threadLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    useEffect(() => {
        if (dataProcessingAccepted) {
            setTimeout(() => {
                setConversationId(CONVERSATION_ID)
                askMax('Show me a complex SQL query')
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}

export const SearchSessionRecordingsTool: StoryFn = () => {
    // This story demonstrates the search_session_recordings tool with nested filter groups
    // showcasing the fix for proper rendering of nested OR/AND groups
    const toolCallMessage: AssistantMessage = {
        type: AssistantMessageType.Assistant,
        content: 'Let me search for those recordings...',
        id: 'search-recordings-msg',
        tool_calls: [
            {
                id: 'search_tool_1',
                name: 'search_session_recordings',
                type: 'tool_call',
                args: {},
            },
        ],
    }

    // Tool call result with nested filter groups: (Chrome AND Mac) OR (Firefox AND Windows)
    const toolCallResult: AssistantToolCallMessage = {
        type: AssistantMessageType.ToolCall,
        tool_call_id: 'search_tool_1',
        content: 'Found recordings matching your criteria',
        id: 'tool-result-1',
        ui_payload: {
            search_session_recordings: {
                date_from: '-7d',
                date_to: null,
                duration: [],
                filter_group: {
                    type: FilterLogicalOperator.Or,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    type: PropertyFilterType.Event,
                                    key: 'browser',
                                    value: 'Chrome',
                                    operator: PropertyOperator.Exact,
                                },
                                {
                                    type: PropertyFilterType.Event,
                                    key: '$os',
                                    value: 'Mac OS X',
                                    operator: PropertyOperator.Exact,
                                },
                            ],
                        },
                        {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    type: PropertyFilterType.Event,
                                    key: 'browser',
                                    value: 'Firefox',
                                    operator: PropertyOperator.Exact,
                                },
                                {
                                    type: PropertyFilterType.Event,
                                    key: '$os',
                                    value: 'Windows',
                                    operator: PropertyOperator.Exact,
                                },
                            ],
                        },
                    ],
                },
            },
        },
    }

    useStorybookMocks({
        post: {
            '/api/environments/:team_id/conversations/': (_, res, ctx) =>
                res(
                    ctx.text(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
                            'event: message',
                            `data: ${JSON.stringify({
                                ...humanMessage,
                                content:
                                    'Show me recordings where users are on Chrome with Mac OR Firefox with Windows',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallMessage)}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallResult)}`,
                        ])
                    )
                ),
        },
    })

    const { setConversationId } = useActions(maxLogic({ tabId: 'storybook' }))
    const threadLogic = maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null, tabId: 'storybook' })
    const { askMax } = useActions(threadLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    useEffect(() => {
        if (dataProcessingAccepted) {
            setTimeout(() => {
                setConversationId(CONVERSATION_ID)
                askMax('Show me recordings where users are on Chrome with Mac OR Firefox with Windows')
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}
SearchSessionRecordingsTool.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

function generateChunk(events: string[]): string {
    return events.map((event) => (event.startsWith('event:') ? `${event}\n` : `${event}\n\n`)).join('')
}
