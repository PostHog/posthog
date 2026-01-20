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
import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { Meta, StoryFn } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { twMerge } from 'tailwind-merge'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import {
    AssistantMessage,
    AssistantMessageType,
    AssistantToolCallMessage,
    MultiVisualizationMessage,
} from '~/queries/schema/schema-assistant-messages'
import { ArtifactContentType, NotebookArtifactContent } from '~/queries/schema/schema-assistant-messages'
import { FunnelsQuery, TrendsQuery } from '~/queries/schema/schema-general'
import { recordings } from '~/scenes/session-recordings/__mocks__/recordings'
import { FilterLogicalOperator, InsightShortId, PropertyFilterType, PropertyOperator } from '~/types'

import { MaxInstance, MaxInstanceProps } from './Max'
import conversationList from './__mocks__/conversationList.json'
import { ToolRegistration } from './max-constants'
import { AlertEntry, ChangelogEntry, maxChangelogLogic } from './maxChangelogLogic'
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
                        user: MOCK_DEFAULT_BASIC_USER,
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

export const ThreadWithBillingLimitExceeded: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/conversations/': (_, res, ctx) =>
                // Testing billing limit exceeded error (402 Payment Required)
                res(
                    ctx.status(402),
                    ctx.json({
                        detail: 'Your organization reached its AI credit usage limit. Increase the limits in [Billing](/organization/billing), or ask an org admin to do so.',
                    })
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
                askMax(humanMessage.content)
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}

export const ThreadWithQuickReplies: StoryFn = () => {
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

export const SharedThread: StoryFn = () => {
    const sharedConversationId = 'shared-conversation-123'

    useStorybookMocks({
        get: {
            '/api/environments/:team_id/conversations/': () => [200, conversationList],
            [`/api/environments/:team_id/conversations/${sharedConversationId}/`]: () => [
                200,
                {
                    id: sharedConversationId,
                    status: 'idle',
                    title: 'Shared Analysis: User Retention Insights',
                    created_at: '2025-01-15T10:30:00.000000Z',
                    updated_at: '2025-01-15T11:45:00.000000Z',
                    user: {
                        id: 1337, // Different user from MOCK_DEFAULT_BASIC_USER
                        uuid: 'ANOTHER_USER_UUID',
                        email: 'another@test.com',
                        first_name: 'Another',
                        last_name: 'User',
                    },
                    messages: [
                        {
                            id: 'msg-1',
                            content: 'Can you analyze our user retention patterns and suggest improvements?',
                            type: 'human',
                            created_at: '2025-01-15T10:30:00.000000Z',
                        },
                        {
                            id: 'msg-2',
                            content:
                                "I'll analyze your user retention patterns. Let me start by examining your data.\n\nBased on the analysis, I can see several key insights:\n\n1. **Day 1 retention**: 45% of users return the next day\n2. **Week 1 retention**: 28% of users are still active after 7 days\n3. **Month 1 retention**: 15% of users remain engaged after 30 days\n\n**Key findings:**\n- Mobile users have 20% higher retention than desktop users\n- Users who complete onboarding have 3x better retention\n- Peak usage occurs between 6-9 PM local time\n\n**Recommendations:**\n1. Improve onboarding completion rate\n2. Implement mobile-first features\n3. Add engagement features for the 6-9 PM window\n4. Create re-engagement campaigns for users who drop off after day 1",
                            type: 'ai',
                            created_at: '2025-01-15T11:45:00.000000Z',
                        },
                    ],
                },
            ],
        },
    })

    const { setConversationId } = useActions(maxLogic({ tabId: 'storybook' }))

    useEffect(() => {
        // Simulate loading a shared conversation via URL parameter
        setConversationId(sharedConversationId)
    }, [setConversationId])

    return <Template />
}
SharedThread.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
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
                    user: MOCK_DEFAULT_BASIC_USER,
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
            description: 'PostHog AI can query insights and their properties',
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
            description: 'PostHog AI can manage cohorts and their properties',
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
            description: 'PostHog AI can manage feature flags and their properties',
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
                name: 'create_insight',
                type: 'tool_call',
                args: {},
            },
            {
                id: 'task_2',
                name: 'create_insight',
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
                name: 'create_insight',
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
                name: 'create_insight',
                type: 'tool_call',
                args: {},
            },
            {
                id: 'task_4',
                name: 'create_insight',
                type: 'tool_call',
                args: {},
            },
            {
                id: 'task_5',
                name: 'create_insight',
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

export const SearchSessionRecordingsEmpty: StoryFn = () => {
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
SearchSessionRecordingsEmpty.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const SearchSessionRecordingsWithResults: StoryFn = () => {
    const toolCallMessage: AssistantMessage = {
        type: AssistantMessageType.Assistant,
        content: 'Let me search for those recordings...',
        id: 'search-recordings-with-results-msg',
        tool_calls: [
            {
                id: 'search_tool_1',
                name: 'search_session_recordings',
                type: 'tool_call',
                args: {},
            },
        ],
    }

    // Tool call result with filter for Microsoft Edge on Linux
    const toolCallResult: AssistantToolCallMessage = {
        type: AssistantMessageType.ToolCall,
        tool_call_id: 'search_tool_1',
        content: 'Found 2 recordings matching your criteria',
        id: 'tool-result-with-recordings-1',
        ui_payload: {
            search_session_recordings: {
                date_from: '-7d',
                date_to: null,
                duration: [],
                filter_group: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    type: PropertyFilterType.Event,
                                    key: '$browser',
                                    value: 'Microsoft Edge',
                                    operator: PropertyOperator.Exact,
                                },
                                {
                                    type: PropertyFilterType.Event,
                                    key: '$os',
                                    value: 'Linux',
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
                                content: 'Show me recordings where users are on Microsoft Edge with Linux',
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
                askMax('Show me recordings where users are on Microsoft Edge with Linux')
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}
SearchSessionRecordingsWithResults.decorators = [
    mswDecorator({
        get: {
            '/api/environments/:team_id/session_recordings': (req) => {
                const version = req.url.searchParams.get('version')
                return [
                    200,
                    {
                        has_next: false,
                        results: recordings,
                        version,
                    },
                ]
            },
        },
    }),
]
SearchSessionRecordingsWithResults.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const ThreadWithMultiQuestionForm: StoryFn = () => {
    // Multi-question form with several questions - uses tool_calls format
    const formQuestions = [
        {
            id: 'use_case',
            question: 'What is your primary use case for PostHog?',
            options: [
                { value: 'Product Analytics' },
                { value: 'A/B Testing' },
                { value: 'Session Replay' },
                { value: 'User Surveys' },
            ],
            allow_custom_answer: true,
        },
        {
            id: 'team_size',
            question: 'How large is your team?',
            options: [
                { value: 'Just me' },
                { value: '2-10 people' },
                { value: '11-50 people' },
                { value: '50+ people' },
            ],
            allow_custom_answer: false,
        },
        {
            id: 'experience',
            question: 'How familiar are you with analytics tools?',
            options: [{ value: 'Beginner' }, { value: 'Intermediate' }, { value: 'Expert' }],
        },
    ]

    const multiQuestionFormMessage: AssistantMessage = {
        type: AssistantMessageType.Assistant,
        content: 'To help you better, I need to understand your needs. Please answer these quick questions:',
        id: 'multi-question-form-msg',
        tool_calls: [
            {
                id: 'create-form-tool-call-1',
                name: 'create_form',
                args: { questions: formQuestions },
                type: 'tool_call',
            },
        ],
    }

    const toolCallResponseMessage: AssistantToolCallMessage = {
        type: AssistantMessageType.ToolCall,
        content: 'The user has not answered the questions yet.',
        id: 'tool-call-response-1',
        tool_call_id: 'create-form-tool-call-1',
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
                                content: 'Help me get started with PostHog',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(multiQuestionFormMessage)}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallResponseMessage)}`,
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
                askMax('Help me get started with PostHog')
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}
ThreadWithMultiQuestionForm.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const ThreadWithSingleQuestionForm: StoryFn = () => {
    // Single question form - uses tool_calls format
    const formQuestions = [
        {
            id: 'data_volume',
            question: 'What is your approximate monthly event volume?',
            options: [
                { value: 'Under 1 million events' },
                { value: '1-10 million events' },
                { value: '10-100 million events' },
                { value: 'Over 100 million events' },
            ],
            allow_custom_answer: true,
        },
    ]

    const singleQuestionFormMessage: AssistantMessage = {
        type: AssistantMessageType.Assistant,
        content: 'Before I proceed, I need to know:',
        id: 'single-question-form-msg',
        tool_calls: [
            {
                id: 'create-form-tool-call-2',
                name: 'create_form',
                args: { questions: formQuestions },
                type: 'tool_call',
            },
        ],
    }

    const toolCallResponseMessage: AssistantToolCallMessage = {
        type: AssistantMessageType.ToolCall,
        content: 'The user has not answered the questions yet.',
        id: 'tool-call-response-2',
        tool_call_id: 'create-form-tool-call-2',
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
                                content: 'What pricing plan should I choose?',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(singleQuestionFormMessage)}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallResponseMessage)}`,
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
                askMax('What pricing plan should I choose?')
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}
ThreadWithSingleQuestionForm.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const ThreadWithMultiQuestionFormLongContent: StoryFn = () => {
    // Form with long questions and answers - agent asking for confirmation before research
    const formQuestions = [
        {
            id: 'research_scope',
            question:
                'I found multiple potential areas to investigate regarding your user retention issues. Which aspect should I prioritize in my analysis?',
            options: [
                { value: 'Onboarding flow completion rates and drop-off points across different user segments' },
                { value: 'Feature adoption patterns and correlation with long-term retention metrics' },
                { value: 'User engagement frequency analysis including session duration and return visit patterns' },
                { value: 'Cohort-based comparison of retained vs churned users over the past 6 months' },
            ],
            allow_custom_answer: true,
        },
        {
            id: 'data_timeframe',
            question:
                'What time period should I focus on for this analysis? Longer periods provide more data but may include outdated patterns, while shorter periods give more recent insights but with less statistical significance.',
            options: [
                { value: 'Last 30 days - Most recent data, best for identifying current issues' },
                { value: 'Last 90 days - Good balance of recency and data volume' },
                { value: 'Last 6 months - Comprehensive view including seasonal variations' },
                { value: 'Last 12 months - Full year analysis for long-term trend identification' },
            ],
            allow_custom_answer: false,
        },
        {
            id: 'user_segment',
            question:
                'Should I focus on a specific user segment, or analyze all users? Focusing on a segment can provide more actionable insights for that group, while analyzing all users gives a broader picture.',
            options: [
                { value: 'All users - Comprehensive analysis across the entire user base' },
                { value: 'New users (signed up in last 30 days) - Focus on early retention' },
                { value: 'Power users (top 20% by activity) - Understand what keeps engaged users' },
                { value: 'At-risk users (declining activity) - Identify churn prevention opportunities' },
            ],
            allow_custom_answer: true,
        },
        {
            id: 'output_format',
            question:
                'How would you like me to present the findings? I can create different types of deliverables depending on your needs and who will be reviewing the results.',
            options: [
                {
                    value: 'Executive summary with key findings and recommended actions (best for stakeholder presentations)',
                },
                { value: 'Detailed analytical report with methodology, data tables, and statistical analysis' },
                { value: 'Interactive dashboard with visualizations that you can explore and filter' },
                { value: 'Prioritized list of action items with expected impact and implementation complexity' },
            ],
            allow_custom_answer: true,
        },
    ]

    const longContentFormMessage: AssistantMessage = {
        type: AssistantMessageType.Assistant,
        content:
            "I've analyzed your request and identified several areas that need investigation. Before I proceed with the deep research, I need to confirm a few things to ensure I focus on what matters most to you.",
        id: 'long-content-form-msg',
        tool_calls: [
            {
                id: 'create-form-tool-call-3',
                name: 'create_form',
                args: { questions: formQuestions },
                type: 'tool_call',
            },
        ],
    }

    const toolCallResponseMessage: AssistantToolCallMessage = {
        type: AssistantMessageType.ToolCall,
        content: 'The user has not answered the questions yet.',
        id: 'tool-call-response-3',
        tool_call_id: 'create-form-tool-call-3',
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
                                    'Can you help me understand why our user retention has been declining? I need a comprehensive analysis.',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(longContentFormMessage)}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallResponseMessage)}`,
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
                askMax(
                    'Can you help me understand why our user retention has been declining? I need a comprehensive analysis.'
                )
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}
ThreadWithMultiQuestionFormLongContent.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const ThreadWithMultiQuestionFormNoCustomAnswer: StoryFn = () => {
    // Form without custom answer options - uses tool_calls format
    const formQuestions = [
        {
            id: 'priority',
            question: 'What is your top priority right now?',
            options: [
                { value: 'Growing user base' },
                { value: 'Improving retention' },
                { value: 'Increasing conversion' },
                { value: 'Boosting engagement' },
            ],
            allow_custom_answer: false,
        },
        {
            id: 'timeline',
            question: 'What is your timeline?',
            options: [{ value: 'This week' }, { value: 'This month' }, { value: 'This quarter' }],
            allow_custom_answer: false,
        },
    ]

    const formMessage: AssistantMessage = {
        type: AssistantMessageType.Assistant,
        content: 'Please select from the following options:',
        id: 'no-custom-form-msg',
        tool_calls: [
            {
                id: 'create-form-tool-call-4',
                name: 'create_form',
                args: { questions: formQuestions },
                type: 'tool_call',
            },
        ],
    }

    const toolCallResponseMessage: AssistantToolCallMessage = {
        type: AssistantMessageType.ToolCall,
        content: 'The user has not answered the questions yet.',
        id: 'tool-call-response-4',
        tool_call_id: 'create-form-tool-call-4',
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
                                content: 'Help me prioritize my analytics work',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(formMessage)}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallResponseMessage)}`,
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
                askMax('Help me prioritize my analytics work')
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}
ThreadWithMultiQuestionFormNoCustomAnswer.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

function generateChunk(events: string[]): string {
    return events.map((event) => (event.startsWith('event:') ? `${event}\n` : `${event}\n\n`)).join('')
}

// Notebook Artifact Stories

export const NotebookArtifactMarkdownOnly: StoryFn = () => {
    const notebookContent: NotebookArtifactContent = {
        content_type: ArtifactContentType.Notebook,
        title: 'User Retention Analysis',
        blocks: [
            {
                type: 'markdown',
                content:
                    '## User Retention Analysis\n\nThis notebook contains an analysis of user retention patterns over the last 90 days.',
            },
            {
                type: 'markdown',
                content:
                    '### Key Findings\n\n- Day 1 retention: **45%** of users return the next day\n- Week 1 retention: **28%** of users are still active after 7 days\n- Month 1 retention: **15%** of users remain engaged after 30 days',
            },
            {
                type: 'markdown',
                content:
                    '### Recommendations\n\n1. Improve onboarding completion rate\n2. Implement mobile-first features\n3. Add engagement features for the 6-9 PM window\n4. Create re-engagement campaigns for users who drop off after day 1',
            },
        ],
    }

    const notebookArtifactMessage = {
        type: AssistantMessageType.Artifact,
        artifact_id: 'notebook-markdown-1',
        source: 'artifact',
        content: notebookContent,
        id: 'notebook-artifact-msg-1',
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
                                content: 'Create a retention analysis notebook',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(notebookArtifactMessage)}`,
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
                askMax('Create a retention analysis notebook')
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}

export const NotebookArtifactWithVisualizations: StoryFn = () => {
    const notebookContent: NotebookArtifactContent = {
        content_type: ArtifactContentType.Notebook,
        title: 'Dashboard Analysis',
        blocks: [
            {
                type: 'markdown',
                content: '## Dashboard Analysis\n\nAnalyzing key product metrics.',
            },
            {
                type: 'visualization',
                query: {
                    kind: 'TrendsQuery',
                    series: [{ event: '$pageview', name: 'Pageviews' }],
                    dateRange: { date_from: '-30d' },
                } as TrendsQuery,
                title: 'Daily Active Users',
            },
            {
                type: 'markdown',
                content: 'The chart above shows our daily active users trend. Note the consistent growth pattern.',
            },
            {
                type: 'visualization',
                query: {
                    kind: 'FunnelsQuery',
                    series: [{ event: 'user signed up' }, { event: 'viewed product' }, { event: 'completed purchase' }],
                } as FunnelsQuery,
                title: 'Conversion Funnel',
            },
        ],
    }

    const notebookArtifactMessage = {
        type: AssistantMessageType.Artifact,
        artifact_id: 'notebook-viz-1',
        source: 'artifact',
        content: notebookContent,
        id: 'notebook-artifact-msg-2',
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
                                content: 'Create a dashboard analysis notebook with charts',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(notebookArtifactMessage)}`,
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
                askMax('Create a dashboard analysis notebook with charts')
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}

export const NotebookArtifactMixedContent: StoryFn = () => {
    const notebookContent: NotebookArtifactContent = {
        content_type: ArtifactContentType.Notebook,
        title: 'Complete Product Analysis',
        blocks: [
            {
                type: 'markdown',
                content:
                    '# Complete Product Analysis\n\nThis comprehensive notebook covers user behavior, funnel analysis, and session replays.',
            },
            {
                type: 'markdown',
                content: '## 1. User Engagement Trends',
            },
            {
                type: 'visualization',
                query: {
                    kind: 'TrendsQuery',
                    series: [{ event: '$pageview', name: 'Page Views' }],
                    dateRange: { date_from: '-30d' },
                } as TrendsQuery,
                title: 'User Engagement',
            },
            {
                type: 'markdown',
                content: '## 2. Conversion Funnel\n\nOur main conversion funnel from signup to purchase:',
            },
            {
                type: 'visualization',
                query: {
                    kind: 'FunnelsQuery',
                    series: [{ event: 'user signed up' }, { event: 'added to cart' }, { event: 'completed purchase' }],
                } as FunnelsQuery,
                title: 'Purchase Funnel',
            },
            {
                type: 'markdown',
                content:
                    '## 3. User Session Analysis\n\nHere is an example session showing a user completing the checkout flow:',
            },
            {
                type: 'session_replay',
                session_id: 'session-abc123',
                timestamp_ms: 1704067200000,
                title: 'Checkout Flow Example',
            },
            {
                type: 'markdown',
                content:
                    '## Conclusions\n\n- User engagement is growing steadily\n- The checkout funnel has a 15% drop-off at the payment step\n- Session replays reveal UX friction in the cart page',
            },
        ],
    }

    const notebookArtifactMessage = {
        type: AssistantMessageType.Artifact,
        artifact_id: 'notebook-mixed-1',
        source: 'artifact',
        content: notebookContent,
        id: 'notebook-artifact-msg-3',
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
                                content: 'Create a comprehensive product analysis notebook',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(notebookArtifactMessage)}`,
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
                askMax('Create a comprehensive product analysis notebook')
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}

export const NotebookArtifactWithLoadingAndErrors: StoryFn = () => {
    const notebookContent: NotebookArtifactContent = {
        content_type: ArtifactContentType.Notebook,
        title: 'Analysis with Loading States',
        blocks: [
            {
                type: 'markdown',
                content: '# Analysis with Loading States\n\nThis notebook demonstrates loading and error states.',
            },
            {
                type: 'visualization',
                query: {
                    kind: 'TrendsQuery',
                    series: [{ event: '$pageview', name: 'Page Views' }],
                    dateRange: { date_from: '-7d' },
                } as TrendsQuery,
                title: 'Successfully Loaded Chart',
            },
            {
                type: 'markdown',
                content: '## Pending Visualization\n\nThe following chart is still loading:',
            },
            {
                type: 'loading',
                artifact_id: 'pending-viz-123',
            },
            {
                type: 'markdown',
                content: '## Missing Visualization\n\nThe following chart could not be found:',
            },
            {
                type: 'error',
                message: 'Visualization not found: missing-artifact-456',
                artifact_id: 'missing-artifact-456',
            },
            {
                type: 'markdown',
                content: '## Conclusions\n\nThis demonstrates how the notebook handles different block states.',
            },
        ],
    }

    const notebookArtifactMessage = {
        type: AssistantMessageType.Artifact,
        artifact_id: 'notebook-loading-errors-1',
        source: 'artifact',
        content: notebookContent,
        id: 'notebook-artifact-msg-loading-errors',
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
                                content: 'Show me an analysis with loading and error states',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(notebookArtifactMessage)}`,
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
                askMax('Show me an analysis with loading and error states')
            }, 0)
        }
    }, [dataProcessingAccepted, setConversationId, askMax])

    if (!dataProcessingAccepted) {
        return <></>
    }

    return <Template />
}

// Changelog Stories

const SAMPLE_CHANGELOG_ENTRIES: ChangelogEntry[] = [
    {
        title: 'SQL generation',
        description: 'Max can now write and run SQL queries for you',
        tag: 'new',
    },
    {
        title: 'Faster responses',
        description: 'Improved response times by up to 40%',
        tag: 'improved',
    },
    {
        title: 'Chart editing',
        description: 'Edit visualization settings directly in conversation',
        tag: 'beta',
    },
]

const SAMPLE_WARNING_ALERT: AlertEntry = {
    title: 'Service degraded',
    description: 'Some AI features may be slower than usual',
    severity: 'warning',
}

const SAMPLE_OUTAGE_ALERT: AlertEntry = {
    title: 'Service outage',
    description: 'AI features are temporarily unavailable. We are working on a fix.',
    severity: 'error',
}

export const ChangelogOnly: StoryFn = () => {
    const { setEntries, openChangelog } = useActions(maxChangelogLogic)

    useEffect(() => {
        setEntries(SAMPLE_CHANGELOG_ENTRIES)
        setTimeout(() => openChangelog(), 100)
    }, [setEntries, openChangelog])

    return <Template />
}
ChangelogOnly.parameters = {
    featureFlags: ['posthog-ai-changelog'],
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const AlertsOnly: StoryFn = () => {
    const { setAlerts, openChangelog } = useActions(maxChangelogLogic)

    useEffect(() => {
        setAlerts([SAMPLE_WARNING_ALERT])
        setTimeout(() => openChangelog(), 100)
    }, [setAlerts, openChangelog])

    return <Template />
}
AlertsOnly.parameters = {
    featureFlags: ['posthog-ai-alerts'],
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const OutageAlert: StoryFn = () => {
    const { setAlerts, openChangelog } = useActions(maxChangelogLogic)

    useEffect(() => {
        setAlerts([SAMPLE_OUTAGE_ALERT])
        setTimeout(() => openChangelog(), 100)
    }, [setAlerts, openChangelog])

    return <Template />
}
OutageAlert.parameters = {
    featureFlags: ['posthog-ai-alerts'],
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const AlertsWithChangelog: StoryFn = () => {
    const { setEntries, setAlerts, openChangelog } = useActions(maxChangelogLogic)

    useEffect(() => {
        setEntries(SAMPLE_CHANGELOG_ENTRIES)
        setAlerts([SAMPLE_WARNING_ALERT])
        setTimeout(() => openChangelog(), 100)
    }, [setEntries, setAlerts, openChangelog])

    return <Template />
}
AlertsWithChangelog.parameters = {
    featureFlags: ['posthog-ai-changelog', 'posthog-ai-alerts'],
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const OutageWithChangelog: StoryFn = () => {
    const { setEntries, setAlerts, openChangelog } = useActions(maxChangelogLogic)

    useEffect(() => {
        setEntries(SAMPLE_CHANGELOG_ENTRIES)
        setAlerts([SAMPLE_OUTAGE_ALERT])
        setTimeout(() => openChangelog(), 100)
    }, [setEntries, setAlerts, openChangelog])

    return <Template />
}
OutageWithChangelog.parameters = {
    featureFlags: ['posthog-ai-changelog', 'posthog-ai-alerts'],
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const MultipleAlerts: StoryFn = () => {
    const { setEntries, setAlerts, openChangelog } = useActions(maxChangelogLogic)

    useEffect(() => {
        setEntries(SAMPLE_CHANGELOG_ENTRIES)
        setAlerts([SAMPLE_WARNING_ALERT, SAMPLE_OUTAGE_ALERT])
        setTimeout(() => openChangelog(), 100)
    }, [setEntries, setAlerts, openChangelog])

    return <Template />
}
MultipleAlerts.parameters = {
    featureFlags: ['posthog-ai-changelog', 'posthog-ai-alerts'],
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}
