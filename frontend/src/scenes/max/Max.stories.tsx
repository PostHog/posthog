import { Meta, StoryFn } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'
import { useEffect } from 'react'
import { twMerge } from 'tailwind-merge'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { FunnelsQuery, TrendsQuery } from '~/queries/schema/schema-general'
import { InsightShortId } from '~/types'

import {
    chatResponseChunk,
    CONVERSATION_ID,
    failureChunk,
    formChunk,
    generationFailureChunk,
    humanMessage,
    longResponseChunk,
} from './__mocks__/chatResponse.mocks'
import conversationList from './__mocks__/conversationList.json'
import { MaxInstance, MaxInstanceProps } from './Max'
import { maxContextLogic } from './maxContextLogic'
import { MaxFloatingInput } from './MaxFloatingInput'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic, QUESTION_SUGGESTIONS_DATA } from './maxLogic'
import { maxThreadLogic } from './maxThreadLogic'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import type { AssistantContextualTool } from '~/queries/schema/schema-assistant-messages'
import { FEATURE_FLAGS } from 'lib/constants'

const meta: Meta = {
    title: 'Scenes-App/Max AI',
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
        featureFlags: [FEATURE_FLAGS.ARTIFICIAL_HOG, FEATURE_FLAGS.FLOATING_ARTIFICIAL_HOG],
    },
}
export default meta

const Template = ({ className, ...props }: MaxInstanceProps & { className?: string }): JSX.Element => {
    return (
        <div className={twMerge('relative flex flex-col h-fit', className)}>
            <MaxInstance {...props} />
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
    const { setConversationId } = useActions(maxLogic)
    const { askMax } = useActions(maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null }))
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

    const { setConversationId } = useActions(maxLogic)
    const threadLogic = maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null })
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

    const { setConversationId } = useActions(maxLogic)
    const threadLogic = maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null })
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

    const { setConversationId } = useActions(maxLogic)
    const threadLogic = maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null })
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

    const { setConversationId } = useActions(maxLogic)
    const threadLogic = maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null })
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

    const { setConversationId } = useActions(maxLogic)
    const threadLogic = maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null })
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

    const { setConversationId } = useActions(maxLogic)
    const threadLogic = maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null })
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

    const { setConversationId } = useActions(maxLogic)

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

    const { setConversationId } = useActions(maxLogic)

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

    const { setConversationId } = useActions(maxLogic)

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

    const { setConversationId } = useActions(maxLogic)

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

    const { toggleConversationHistory } = useActions(maxLogic)

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

    const { toggleConversationHistory } = useActions(maxLogic)

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

    const { toggleConversationHistory } = useActions(maxLogic)

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
    const { setActiveGroup } = useActions(maxLogic)

    useEffect(() => {
        // The largest group is the set up group
        setActiveGroup(QUESTION_SUGGESTIONS_DATA[3])
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
    const { setActiveGroup } = useActions(maxLogic)

    useEffect(() => {
        // The largest group is the set up group
        setActiveGroup(QUESTION_SUGGESTIONS_DATA[3])
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

    const { conversation } = useValues(maxLogic)
    const { setConversationId } = useActions(maxLogic)
    const logic = maxThreadLogic({ conversationId: 'poem', conversation })
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

export const FloatingInput: StoryFn = () => {
    const { closeSidePanel } = useActions(sidePanelLogic)
    const { setIsFloatingMaxExpanded } = useActions(maxGlobalLogic)
    useEffect(() => {
        closeSidePanel()
        setIsFloatingMaxExpanded(false)
    }, [])

    return <MaxFloatingInput />
}

export const ExpandedFloatingInput: StoryFn = () => {
    const { setIsFloatingMaxExpanded } = useActions(maxGlobalLogic)
    useEffect(() => {
        setIsFloatingMaxExpanded(true)
    }, [])

    return <MaxFloatingInput />
}

export const ExpandedFloatingInputWithContextualTools: StoryFn = () => {
    const { registerTool } = useActions(maxGlobalLogic)

    useEffect(() => {
        // Register sample contextual tools
        registerTool({
            name: 'create_insight' as AssistantContextualTool,
            displayName: 'Create insight',
            description: 'Max can create a new insight',
            context: {
                dashboard_id: 'test-dashboard',
                available_events: ['$pageview', '$identify', 'button_clicked'],
                current_filters: { date_range: 'last_7_days' },
            },
            callback: (toolOutput) => {
                console.info('Creating insight:', toolOutput)
            },
        })

        registerTool({
            name: 'analyze_funnel' as AssistantContextualTool,
            displayName: 'Analyze funnel',
            description: 'Max can analyze a funnel',
            context: {
                existing_funnels: ['signup_funnel', 'checkout_funnel'],
                conversion_metrics: { signup_rate: 0.15, checkout_rate: 0.08 },
            },
            callback: (toolOutput) => {
                console.info('Analyzing funnel:', toolOutput)
            },
        })

        registerTool({
            name: 'export_data' as AssistantContextualTool,
            displayName: 'Export data',
            description: 'Max can export data in various formats',
            context: {
                available_formats: ['csv', 'json', 'parquet'],
                current_query: { event: '$pageview', breakdown: 'browser' },
            },
            callback: (toolOutput) => {
                console.info('Exporting data:', toolOutput)
            },
        })
    }, [registerTool])

    return <MaxFloatingInput />
}

export const ExpandedFloatingInputWithSuggestions: StoryFn = () => {
    const { setIsFloatingMaxExpanded, setShowFloatingMaxSuggestions } = useActions(maxGlobalLogic)
    useEffect(() => {
        setIsFloatingMaxExpanded(true)
        setShowFloatingMaxSuggestions(true)
    }, [setIsFloatingMaxExpanded, setShowFloatingMaxSuggestions])

    return <MaxFloatingInput />
}

export const ExpandedFloatingInputMobileView: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/organizations/@current/': () => [
                200,
                {
                    ...MOCK_DEFAULT_ORGANIZATION,
                    is_ai_data_processing_approved: true,
                },
            ],
        },
    })

    return <MaxFloatingInput />
}
ExpandedFloatingInputMobileView.parameters = {
    viewport: {
        defaultViewport: 'mobile2',
    },
}

export const ExpandedFloatingInputThread: StoryFn = () => {
    const { setIsFloatingMaxExpanded } = useActions(maxGlobalLogic)
    const { setConversationId } = useActions(maxLogic)
    const threadLogic = maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null })
    const { askMax } = useActions(threadLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    useEffect(() => {
        setIsFloatingMaxExpanded(true)
    }, [setIsFloatingMaxExpanded])

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

    return <MaxFloatingInput />
}
ExpandedFloatingInputThread.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const MaxInstanceWithContextualTools: StoryFn = () => {
    const { registerTool } = useActions(maxGlobalLogic)

    useEffect(() => {
        // Register various contextual tools for MaxInstance
        registerTool({
            name: 'query_insights' as AssistantContextualTool,
            displayName: 'Query insights',
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
            name: 'manage_cohorts' as AssistantContextualTool,
            displayName: 'Manage cohorts',
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
            name: 'feature_flags' as AssistantContextualTool,
            displayName: 'Feature flags',
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
