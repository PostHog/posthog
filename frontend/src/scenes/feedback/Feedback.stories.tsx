import { ComponentMeta } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'
import { Feedback } from './Feedback'
import { feedbackLogic } from './feedbackLogic'

export default {
    title: 'Scenes-App/Feedback',
    component: Feedback,
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
} as ComponentMeta<typeof Feedback>

export const InAppFeedbackInstructions = (): JSX.Element => {
    useEffect(() => {
        feedbackLogic.mount()
        router.actions.push(urls.feedback())
    }, [])
    return <App />
}

export const InAppFeedbackTable = (): JSX.Element => {
    useEffect(() => {
        feedbackLogic.mount()
        // TODO Mock the events response with the following ([
        //     {
        //         id: '0186be3d-a537-0000-241d-4bcbc3a58e3d',
        //         distinct_id: '186be3d756accb-0f8714ba5aca8f-1f525634-1d73c0-186be3d756b237e',
        //         properties: {
        //             $feedback: 'Test',
        //         },
        //         event: 'Feedback Sent',
        //         timestamp: '2023-03-07T22:42:36.154000+00:00',
        //         person: {
        //             is_identified: false,
        //             distinct_ids: ['186be3d756accb-0f8714ba5aca8f-1f525634-1d73c0-186be3d756b237e'],
        //             properties: {},
        //         },
        //         elements: [],
        //         elements_chain: '',
        //     },
        // ])
        router.actions.push(urls.feedback())
    }, [])
    return <App />
}
