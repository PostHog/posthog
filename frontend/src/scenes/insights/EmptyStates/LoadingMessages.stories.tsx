import { Meta, StoryFn } from '@storybook/react'

import { BASE_LOADING_MESSAGES, CHRISTMAS_LOADING_MESSAGES, HALLOWEEN_LOADING_MESSAGES } from './EmptyStates'

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
        <div className="flex flex-col gap-2">
            <ul>
                {BASE_LOADING_MESSAGES.map((message, idx) => (
                    <li key={idx}>{message}</li>
                ))}
            </ul>
            <ul>
                {CHRISTMAS_LOADING_MESSAGES.map((message, idx) => (
                    <li key={idx}>{message}</li>
                ))}
            </ul>
            <ul>
                {HALLOWEEN_LOADING_MESSAGES.map((message, idx) => (
                    <li key={idx}>{message}</li>
                ))}
            </ul>
        </div>
    )
}
