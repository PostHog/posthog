import { ComponentMeta } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'
import { Feedback, FeedbackInstructions } from './Feedback'

export default {
    title: 'Scenes-App/Feedback',
    component: Feedback,
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
} as ComponentMeta<typeof Feedback>

export const FeedbackPage = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.feedback())
    }, [])
    return <App />
}

export const Instructions = (): JSX.Element => {
    return <FeedbackInstructions />
}
