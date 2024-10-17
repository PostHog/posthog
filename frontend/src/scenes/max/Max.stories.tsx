import { Meta, StoryFn } from '@storybook/react'
import { BindLogic, useActions } from 'kea'
import { useEffect } from 'react'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'

import chatResponse from './__mocks__/chatResponse.json'
import { MaxInstance } from './Max'
import { maxLogic } from './maxLogic'

const meta: Meta = {
    title: 'Scenes-App/Max AI',
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/chat/': chatResponse,
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
            '/api/projects/:team_id/query/': () => [
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

    const sessionId = 'd210b263-8521-4c5b-b3c4-8e0348df574b'
    return <Template sessionId={sessionId} />
}

export const WelcomeLoadingSuggestions: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/projects/:team_id/query/': (_req, _res, ctx) => [ctx.delay('infinite')],
        },
    })

    const sessionId = 'd210b263-8521-4c5b-b3c4-8e0348df574b'
    return <Template sessionId={sessionId} />
}
WelcomeLoadingSuggestions.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const Thread: StoryFn = () => {
    const sessionId = 'd210b263-8521-4c5b-b3c4-8e0348df574b'

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

    const sessionId = 'd210b263-8521-4c5b-b3c4-8e0348df574b'

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
