import { Meta, StoryFn } from '@storybook/react'

import { LOADING_MESSAGES } from './EmptyStates'

const meta: Meta = {
    title: 'Scenes-App/Insights/Loading Messages',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta

export const LoadingMessages: StoryFn = () => {
    return (
        <div>
            <ul>
                {LOADING_MESSAGES.map((message, idx) => (
                    <li key={idx}>{message}</li>
                ))}
            </ul>
        </div>
    )
}
