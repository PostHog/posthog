import { Meta, StoryFn } from '@storybook/react'
import { BindLogic, useActions, useValues } from 'kea'
import { MOCK_DEFAULT_PROJECT } from 'lib/api.mock'
import { uuid } from 'lib/utils'
import { useEffect, useState } from 'react'
import { projectLogic } from 'scenes/projectLogic'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'

import { chatResponseChunk, failureChunk, generationFailureChunk } from './__mocks__/chatResponse.mocks'
import { MaxInstance } from './Max'
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

const Template = ({ sessionId }: { sessionId: string }): JSX.Element => {
    return (
        <div className="relative flex flex-col h-fit">
            <BindLogic logic={maxLogic} props={{ sessionId }}>
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

    const [sessionId] = useState(uuid())
    return <Template sessionId={sessionId} />
}

export const WelcomeSuggestionsAvailable: StoryFn = () => {
    const { loadCurrentProjectSuccess } = useActions(projectLogic)
    useEffect(() => {
        loadCurrentProjectSuccess({ ...MOCK_DEFAULT_PROJECT, product_description: 'A Storybook test.' })
    })

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
    })

    const [sessionId] = useState(uuid())
    return <Template sessionId={sessionId} />
}
WelcomeLoadingSuggestions.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const Thread: StoryFn = () => {
    const [sessionId] = useState(uuid())

    const { askMax } = useActions(maxLogic({ sessionId }))
    useEffect(() => {
        askMax('What are my most popular pages?')
    }, [])

    return <Template sessionId={sessionId} />
}

export const EmptyThreadLoading: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/query/chat/': (_req, _res, ctx) => [ctx.delay('infinite')],
        },
    })

    const [sessionId] = useState(uuid())

    const { askMax } = useActions(maxLogic({ sessionId }))
    useEffect(() => {
        askMax('What are my most popular pages?')
    }, [])

    return <Template sessionId={sessionId} />
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

    const [sessionId] = useState(uuid())

    const { askMax, setMessageStatus } = useActions(maxLogic({ sessionId }))
    const { thread, threadLoading } = useValues(maxLogic({ sessionId }))
    useEffect(() => {
        askMax('What are my most popular pages?')
    }, [])
    useEffect(() => {
        if (thread.length === 2 && !threadLoading) {
            setMessageStatus(1, 'error')
        }
    }, [thread.length, threadLoading])

    return <Template sessionId={sessionId} />
}

export const ThreadWithFailedGeneration: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/query/chat/': (_, res, ctx) => res(ctx.text(failureChunk)),
        },
    })

    const [sessionId] = useState(uuid())

    const { askMax } = useActions(maxLogic({ sessionId }))
    useEffect(() => {
        askMax('What are my most popular pages?')
    }, [])

    return <Template sessionId={sessionId} />
}
