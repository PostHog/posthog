import { Meta, StoryFn } from '@storybook/react'
import { BindLogic, useActions, useValues } from 'kea'
import { MOCK_DEFAULT_PROJECT } from 'lib/api.mock'
import { useEffect } from 'react'
import { projectLogic } from 'scenes/projectLogic'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'

import { chatResponseChunk, failureChunk, generationFailureChunk } from './__mocks__/chatResponse.mocks'
import { MaxInstance } from './Max'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'

const meta: Meta = {
    title: 'Scenes-App/Max AI',
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/chat/': (_, res, ctx) => res(ctx.text(chatResponseChunk)),
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

// The session ID is hard-coded here, as it's used for randomizing the welcome headline
const SESSION_ID = 'b1b4b3b4-1b3b-4b3b-1b3b4b3b4b3b'

const Template = ({ sessionId: SESSION_ID }: { sessionId: string }): JSX.Element => {
    const { acceptDataProcessing } = useActions(maxGlobalLogic)

    useEffect(() => {
        acceptDataProcessing()
    }, [])

    return (
        <div className="relative flex flex-col h-fit">
            <BindLogic logic={maxLogic} props={{ sessionId: SESSION_ID }}>
                <MaxInstance />
            </BindLogic>
        </div>
    )
}

export const Welcome: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/query/': () => [
                200,
                {
                    questions: [
                        'What are my most popular pages?',
                        'Where are my users located?',
                        'Who are the biggest customers?',
                        'Which feature drives most usage?',
                    ],
                },
            ],
        },
    })
    const { acceptDataProcessing } = useActions(maxGlobalLogic)
    useEffect(() => {
        // We override data processing opt-in to false, so that wee see the welcome screen as a first-time user would
        acceptDataProcessing(false)
    }, [])

    return <Template sessionId={SESSION_ID} />
}

export const WelcomeSuggestionsAvailable: StoryFn = () => {
    const { loadCurrentProjectSuccess } = useActions(projectLogic)

    useEffect(() => {
        loadCurrentProjectSuccess({ ...MOCK_DEFAULT_PROJECT, product_description: 'A Storybook test.' })
    }, [])

    return <Welcome />
}

export const WelcomeLoadingSuggestions: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/query/': (_req, _res, ctx) => [ctx.delay('infinite')],
        },
    })

    const { loadCurrentProjectSuccess } = useActions(projectLogic)

    useEffect(() => {
        loadCurrentProjectSuccess({ ...MOCK_DEFAULT_PROJECT, product_description: 'A Storybook test.' })
    }, [])

    return <Template sessionId={SESSION_ID} />
}
WelcomeLoadingSuggestions.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const Thread: StoryFn = () => {
    const { askMax } = useActions(maxLogic({ sessionId: SESSION_ID }))

    useEffect(() => {
        askMax('What are my most popular pages?')
    }, [])

    return <Template sessionId={SESSION_ID} />
}

export const EmptyThreadLoading: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/query/chat/': (_req, _res, ctx) => [ctx.delay('infinite')],
        },
    })

    const { askMax } = useActions(maxLogic({ sessionId: SESSION_ID }))

    useEffect(() => {
        askMax('What are my most popular pages?')
    }, [])

    return <Template sessionId={SESSION_ID} />
}
EmptyThreadLoading.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const GenerationFailureThread: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/query/chat/': (_, res, ctx) => res(ctx.text(generationFailureChunk)),
        },
    })

    const { askMax, setMessageStatus } = useActions(maxLogic({ sessionId: SESSION_ID }))
    const { threadRaw, threadLoading } = useValues(maxLogic({ sessionId: SESSION_ID }))

    useEffect(() => {
        askMax('What are my most popular pages?')
    }, [])

    useEffect(() => {
        if (threadRaw.length === 2 && !threadLoading) {
            setMessageStatus(1, 'error')
        }
    }, [threadRaw.length, threadLoading])

    return <Template sessionId={SESSION_ID} />
}

export const ThreadWithFailedGeneration: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/query/chat/': (_, res, ctx) => res(ctx.text(failureChunk)),
        },
    })

    const { askMax } = useActions(maxLogic({ sessionId: SESSION_ID }))

    useEffect(() => {
        askMax('What are my most popular pages?')
    }, [])

    return <Template sessionId={SESSION_ID} />
}

export const ThreadWithRateLimit: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/query/chat/': (_, res, ctx) =>
                res(ctx.text(chatResponseChunk), ctx.status(429)),
        },
    })

    const { askMax } = useActions(maxLogic({ sessionId: SESSION_ID }))

    useEffect(() => {
        askMax('Is Bielefeld real?')
    }, [])

    return <Template sessionId={SESSION_ID} />
}
