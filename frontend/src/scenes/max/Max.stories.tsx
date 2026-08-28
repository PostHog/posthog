import {
    CONVERSATION_ID,
    chatResponseChunk,
    chatResponseWithEventContext,
    failureChunk,
    formChunk,
    generationFailureChunk,
    humanMessage,
    longResponseChunk,
} from './__mocks__/chatResponse.mocks'
import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { HttpResponse, delay } from 'msw'
import { useEffect } from 'react'

import { useStorybookMocks } from '~/mocks/browser'
import { FunnelsQuery, TrendsQuery } from '~/queries/schema/schema-general'
import { InsightShortId } from '~/types'

import conversationList from './__mocks__/conversationList.json'
import { maxContextLogic } from './maxContextLogic'
import { maxGlobalLogic } from './maxGlobalLogic'
import { QUESTION_SUGGESTIONS_DATA, maxLogic } from './maxLogic'
import { Template, sharedMeta, useAutoSendOnce } from './maxStoriesShared'
import { maxThreadLogic } from './maxThreadLogic'

const meta: Meta = {
    title: 'Scenes-App/PostHog AI',
    ...sharedMeta,
}
export default meta

type Story = StoryObj<{}>

export const Welcome: Story = {
    render: () => {
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
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const WelcomeFeaturePreviewAutoEnrolled: Story = {
    render: () => {
        return <Template />
    },
    parameters: {
        featureFlags: [],
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const Thread: Story = {
    render: () => {
        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const { askMax } = useActions(
            maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null, panelId: 'storybook' })
        )
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax(humanMessage.content)
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
}

export const EmptyThreadLoading: Story = {
    render: () => {
        useStorybookMocks({
            post: {
                '/api/environments/:team_id/conversations/': async () => {
                    await delay('infinite')
                    return new HttpResponse()
                },
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax(humanMessage.content)
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const GenerationFailureThread: Story = {
    render: () => {
        useStorybookMocks({
            post: {
                '/api/environments/:team_id/conversations/': () => new HttpResponse(generationFailureChunk),
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax, setMessageStatus } = useActions(threadLogic)
        const { threadRaw, threadLoading } = useValues(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax(humanMessage.content)
        })

        useEffect(() => {
            if (threadRaw.length === 2 && !threadLoading) {
                setMessageStatus(1, 'error')
            }
        }, [threadRaw.length, threadLoading, setMessageStatus])

        if (!dataProcessingAccepted) {
            return <></>
        }
        return <Template />
    },
}

export const ThreadWithFailedGeneration: Story = {
    render: () => {
        useStorybookMocks({
            post: {
                '/api/environments/:team_id/conversations/': () => new HttpResponse(failureChunk),
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax(humanMessage.content)
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
}

export const ThreadWithRateLimit: Story = {
    render: () => {
        useStorybookMocks({
            post: {
                // Retry-After header is present so we should be showing its value in the UI
                '/api/environments/:team_id/conversations/': () =>
                    new HttpResponse(chatResponseChunk, { status: 429, headers: { 'Retry-After': '3899' } }),
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax(humanMessage.content)
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
}

export const ThreadWithRateLimitNoRetryAfter: Story = {
    render: () => {
        useStorybookMocks({
            post: {
                // Testing rate limit error when the Retry-After header is MISSING
                '/api/environments/:team_id/conversations/': () => new HttpResponse(chatResponseChunk, { status: 429 }),
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax(humanMessage.content)
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
}

export const ThreadWithBillingLimitExceeded: Story = {
    render: () => {
        useStorybookMocks({
            post: {
                // Testing billing limit exceeded error (402 Payment Required)
                '/api/environments/:team_id/conversations/': () => [
                    402,
                    {
                        detail: 'Your organization reached its AI credit usage limit. Increase the limits in [Billing](/organization/billing), or ask an org admin to do so.',
                    },
                ],
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax(humanMessage.content)
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
}

export const ThreadWithQuickReplies: Story = {
    render: () => {
        useStorybookMocks({
            post: {
                '/api/environments/:team_id/conversations/': () => new HttpResponse(formChunk),
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax(humanMessage.content)
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
}

export const ThreadWithConversationLoading: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/conversations/': async () => {
                    await delay('infinite')
                    return new HttpResponse()
                },
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))

        useEffect(() => {
            setConversationId(CONVERSATION_ID)
        }, [setConversationId])

        return <Template />
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const ThreadWithEmptyConversation: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/conversations/': () => [200, conversationList],
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))

        useEffect(() => {
            setConversationId('empty')
        }, [setConversationId])

        return <Template />
    },
}

export const SharedThread: Story = {
    render: () => {
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

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))

        useEffect(() => {
            // Simulate loading a shared conversation via URL parameter
            setConversationId(sharedConversationId)
        }, [setConversationId])

        return <Template />
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const ThreadWithInProgressConversation: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/conversations/': () => [200, conversationList],
                '/api/environments/:team_id/conversations/in_progress/': async () => {
                    await delay('infinite')
                    return new HttpResponse()
                },
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))

        useEffect(() => {
            setConversationId('in_progress')
        }, [setConversationId])

        return <Template sidePanel />
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const WelcomeWithLatestConversations: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/conversations/': () => [200, conversationList],
            },
        })

        return <Template sidePanel />
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const ChatHistory: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/conversations/': () => [200, conversationList],
            },
        })

        const { toggleConversationHistory } = useActions(maxLogic({ panelId: 'storybook' }))

        useEffect(() => {
            toggleConversationHistory(true)
        }, [toggleConversationHistory])

        return <Template sidePanel />
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const ChatHistoryEmpty: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/conversations/': () => [400],
            },
        })

        const { toggleConversationHistory } = useActions(maxLogic({ panelId: 'storybook' }))

        useEffect(() => {
            toggleConversationHistory(true)
        }, [toggleConversationHistory])

        return <Template sidePanel />
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const ChatHistoryLoading: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/conversations/': async () => {
                    await delay('infinite')
                    return new HttpResponse()
                },
            },
        })

        const { toggleConversationHistory } = useActions(maxLogic({ panelId: 'storybook' }))

        useEffect(() => {
            toggleConversationHistory(true)
        }, [toggleConversationHistory])

        return <Template sidePanel />
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const ThreadWithOpenedSuggestionsMobile: Story = {
    render: () => {
        const { setActiveGroup } = useActions(maxLogic({ panelId: 'storybook' }))

        useEffect(() => {
            // The largest group is the set up group
            if (QUESTION_SUGGESTIONS_DATA[3]) {
                setActiveGroup(QUESTION_SUGGESTIONS_DATA[3])
            }
        }, [setActiveGroup])

        return <Template sidePanel />
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
        viewport: {
            defaultViewport: 'mobile2',
        },
    },
}

export const ThreadWithOpenedSuggestions: Story = {
    render: () => {
        const { setActiveGroup } = useActions(maxLogic({ panelId: 'storybook' }))

        useEffect(() => {
            // The largest group is the set up group
            if (QUESTION_SUGGESTIONS_DATA[3]) {
                setActiveGroup(QUESTION_SUGGESTIONS_DATA[3])
            }
        }, [setActiveGroup])

        return <Template sidePanel />
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const ThreadWithMultipleContextObjects: Story = {
    render: () => {
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
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const ThreadScrollsToBottomOnNewMessages: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/conversations/': () => [200, conversationList],
            },
            post: {
                '/api/environments/:team_id/conversations/': async () => {
                    await delay(100)
                    return new HttpResponse(longResponseChunk)
                },
            },
        })

        const { conversation } = useValues(maxLogic({ panelId: 'storybook' }))
        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const logic = maxThreadLogic({ conversationId: 'poem', conversation, panelId: 'storybook' })
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
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const ChatWithUIContext: Story = {
    render: () => {
        useStorybookMocks({
            post: {
                '/api/environments/:team_id/conversations/': () => new HttpResponse(chatResponseWithEventContext),
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
        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
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

        // After the event is added, start a new conversation (changing the URL) exactly once.
        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted && contextEvents.length > 0, () => {
            setConversationId(CONVERSATION_ID)
            askMax('Tell me about the $pageview event')
        })

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
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}
