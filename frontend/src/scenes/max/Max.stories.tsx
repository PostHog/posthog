import { Meta, StoryFn } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'
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
import { maxLogic, QUESTION_SUGGESTIONS_DATA } from './maxLogic'
import { maxThreadLogic } from './maxThreadLogic'

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
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
        featureFlags: ['artificial-hog'],
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

export const WelcomeFeaturePreviewAutoEnrolled: StoryFn = () => {
    return <Template />
}
WelcomeFeaturePreviewAutoEnrolled.parameters = {
    featureFlags: [],
}

export const Thread: StoryFn = () => {
    const { setConversationId } = useActions(maxLogic)
    const { askMax } = useActions(maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null }))

    useEffect(() => {
        setConversationId(CONVERSATION_ID)
        askMax(humanMessage.content)
    }, [])

    return <Template />
}

export const EmptyThreadLoading: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/conversations/': (_req, _res, ctx) => [ctx.delay('infinite')],
        },
    })

    const { setConversationId } = useActions(maxLogic)
    const { askMax } = useActions(maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null }))

    useEffect(() => {
        setConversationId(CONVERSATION_ID)
        askMax(humanMessage.content)
    }, [])

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

    useEffect(() => {
        setConversationId(CONVERSATION_ID)
        askMax(humanMessage.content)
    }, [])

    useEffect(() => {
        if (threadRaw.length === 2 && !threadLoading) {
            setMessageStatus(1, 'error')
        }
    }, [threadRaw.length, threadLoading])

    return <Template />
}

export const ThreadWithFailedGeneration: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/conversations/': (_, res, ctx) => res(ctx.text(failureChunk)),
        },
    })

    const { setConversationId } = useActions(maxLogic)
    const { askMax } = useActions(maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null }))

    useEffect(() => {
        setConversationId(CONVERSATION_ID)
        askMax(humanMessage.content)
    }, [])

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
    const { askMax } = useActions(maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null }))

    useEffect(() => {
        setConversationId(CONVERSATION_ID)
        askMax('Is Bielefeld real?')
    }, [])

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
    const { askMax } = useActions(maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null }))

    useEffect(() => {
        setConversationId(CONVERSATION_ID)
        askMax('Is Finland real?')
    }, [])

    return <Template />
}

export const ThreadWithForm: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/conversations/': (_, res, ctx) => res(ctx.text(formChunk)),
        },
    })

    const { setConversationId } = useActions(maxLogic)
    const { askMax } = useActions(maxThreadLogic({ conversationId: CONVERSATION_ID, conversation: null }))

    useEffect(() => {
        setConversationId(CONVERSATION_ID)
        askMax(humanMessage.content)
    }, [])

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
    }, [])

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
    }, [])

    return <Template />
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
    }, [])

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
    }, [])

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
    }, [])

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
    }, [])

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
    }, [])

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
    }, [])

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

    const { addOrUpdateContextInsight, enableCurrentPageContext, addOrUpdateActiveInsight } =
        useActions(maxContextLogic)

    useEffect(() => {
        // Add multiple context insights
        addOrUpdateContextInsight('insight-1', {
            short_id: 'insight-1' as InsightShortId,
            name: 'Weekly Active Users',
            description: 'Track weekly active users over time',
            query: {
                kind: 'TrendsQuery',
                series: [{ event: '$pageview' }],
            } as TrendsQuery,
        })

        addOrUpdateContextInsight('insight-2', {
            short_id: 'insight-2' as InsightShortId,
            name: 'Conversion Funnel',
            description: 'User signup to activation funnel',
            query: {
                kind: 'FunnelsQuery',
                series: [{ event: 'sign up' }, { event: 'first action' }],
            } as FunnelsQuery,
        })

        // Add active insights for current page context
        addOrUpdateActiveInsight('active-insight-1', {
            short_id: 'active-insight-1' as InsightShortId,
            name: 'Current Page Metrics',
            description: 'Metrics for the current page',
            query: {
                kind: 'TrendsQuery',
                series: [{ event: '$pageview' }],
            } as TrendsQuery,
        })

        // Enable current page context to show active insights/dashboard
        enableCurrentPageContext()
    }, [])

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
        <div className="h-[800px] overflow-y-auto SidePanel3000__content">
            <Template />
        </div>
    )
}
ThreadScrollsToBottomOnNewMessages.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}
