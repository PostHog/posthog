import { Meta, Story } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'
import { mswDecorator } from '~/mocks/browser'
import { feedbackLogic } from './feedbackLogic'

export default {
    title: 'Scenes-App/Feedback',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        testOptions: {
            excludeNavigationFromSnapshot: true,
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
} as Meta

export const InAppFeedbackTable: Story = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.feedback())
        feedbackLogic.mount()
    }, [])
    return <App />
}

export const InAppFeedbackInstructions: Story = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.feedback())
        feedbackLogic.mount()
        feedbackLogic.actions.toggleInAppFeedbackInstructions()
    }, [])
    return <App />
}
