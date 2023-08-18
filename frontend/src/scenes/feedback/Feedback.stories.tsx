import { StoryFn, Meta } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'
import { mswDecorator } from '~/mocks/browser'
import { feedbackLogic } from './feedbackLogic'
import { inAppFeedbackLogic } from './inAppFeedbackLogic'
import { userInterviewSchedulerLogic } from './userInterviewSchedulerLogic'

const meta: Meta = {
    title: 'Scenes-App/Feedback',
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            excludeNavigationFromSnapshot: true,
            skip: true, // FIXME: Use mockdate in this story
        },
        viewMode: 'story',
        // Might need to add a mockdate here, however when I do it breaks the page
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/events/': require('./__mocks__/events.json'),
                'api/projects/:team_id/insights/trend/': require('./__mocks__/trend.json'),
            },
        }),
    ],
}
export default meta
export const InAppFeedbackTable: StoryFn = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.feedback())
        feedbackLogic.mount()
    }, [])
    return <App />
}

export const InAppFeedbackInstructions: StoryFn = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.feedback())
        inAppFeedbackLogic.mount()
        inAppFeedbackLogic.actions.toggleInAppFeedbackInstructions()
    }, [])
    return <App />
}

export const UserInterviewScheduler: StoryFn = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.feedback())
        feedbackLogic.mount()
        feedbackLogic.actions.setActiveTab('user-interview-scheduler')
    }, [])
    return <App />
}

export const UserInterviewSchedulerInstructions: StoryFn = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.feedback())
        feedbackLogic.mount()
        feedbackLogic.actions.setActiveTab('user-interview-scheduler')
        userInterviewSchedulerLogic.mount()
        userInterviewSchedulerLogic.actions.toggleSchedulerInstructions()
    }, [])
    return <App />
}
