import { Meta, StoryFn } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'
import { useEffect } from 'react'
import { maxSettingsLogic } from 'scenes/settings/environment/maxSettingsLogic'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'

import {
    chatResponseChunk,
    CONVERSATION_ID,
    failureChunk,
    formChunk,
    generationFailureChunk,
    humanMessage,
} from './__mocks__/chatResponse.mocks'
import conversationList from './__mocks__/conversationList.json'
import { MaxInstance, MaxInstanceProps } from './Max'
import { maxLogic } from './maxLogic'

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

const Template = (props: MaxInstanceProps): JSX.Element => {
    return (
        <div className="relative flex flex-col h-fit">
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

export const WelcomeSuggestionsAvailable: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/query/': () => [
                200,
                {
                    questions: [
                        'What are our most popular pages in the blog?',
                        'Where are our new users located?',
                        'Who are the biggest customers using our paid product?',
                        'Which feature drives most usage?',
                    ],
                },
            ],
        },
    })

    const { loadCoreMemorySuccess } = useActions(maxSettingsLogic)

    useEffect(() => {
        loadCoreMemorySuccess({ id: 'x', text: 'A Storybook test.' })
    }, [])

    return <Template />
}

export const WelcomeLoadingSuggestions: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/query/': (_req, _res, ctx) => [ctx.delay('infinite')],
        },
    })

    const { loadCoreMemorySuccess } = useActions(maxSettingsLogic)

    useEffect(() => {
        loadCoreMemorySuccess({ id: 'x', text: 'A Storybook test.' })
    }, [])

    return <Template />
}
WelcomeLoadingSuggestions.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const WelcomeFeaturePreviewAutoEnrolled: StoryFn = () => {
    return <Template />
}
WelcomeFeaturePreviewAutoEnrolled.parameters = {
    featureFlags: [],
}

export const Thread: StoryFn = () => {
    const { askMax } = useActions(maxLogic({ conversationId: CONVERSATION_ID }))

    useEffect(() => {
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

    const { askMax } = useActions(maxLogic({ conversationId: CONVERSATION_ID }))

    useEffect(() => {
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

    const { askMax, setMessageStatus } = useActions(maxLogic({ conversationId: CONVERSATION_ID }))
    const { threadRaw, threadLoading } = useValues(maxLogic({ conversationId: CONVERSATION_ID }))

    useEffect(() => {
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

    const { askMax } = useActions(maxLogic({ conversationId: CONVERSATION_ID }))

    useEffect(() => {
        askMax(humanMessage.content)
    }, [])

    return <Template />
}

export const ThreadWithRateLimit: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/conversations/': (_, res, ctx) =>
                res(ctx.text(chatResponseChunk), ctx.status(429)),
        },
    })

    const { askMax } = useActions(maxLogic({ conversationId: CONVERSATION_ID }))

    useEffect(() => {
        askMax('Is Bielefeld real?')
    }, [])

    return <Template />
}

export const ThreadWithForm: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/conversations/': (_, res, ctx) => res(ctx.text(formChunk)),
        },
    })

    const { askMax } = useActions(maxLogic({ conversationId: CONVERSATION_ID }))

    useEffect(() => {
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

    const { setConversationId } = useActions(maxLogic({ conversationId: CONVERSATION_ID }))

    useEffect(() => {
        setConversationId('test')
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

    const { setConversationId } = useActions(maxLogic({ conversationId: CONVERSATION_ID }))

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

    const { setConversationId } = useActions(maxLogic({ conversationId: CONVERSATION_ID }))

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

export const ChatHistory: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/conversations/': () => [200, conversationList],
        },
    })

    const { toggleConversationHistory } = useActions(maxLogic({ conversationId: CONVERSATION_ID }))

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

    const { toggleConversationHistory } = useActions(maxLogic({ conversationId: CONVERSATION_ID }))

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

    const { toggleConversationHistory } = useActions(maxLogic({ conversationId: CONVERSATION_ID }))

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
