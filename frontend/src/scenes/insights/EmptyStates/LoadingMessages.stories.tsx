import { Meta, StoryObj } from '@storybook/react'

import { BASE_LOADING_MESSAGES, CHRISTMAS_LOADING_MESSAGES, HALLOWEEN_LOADING_MESSAGES } from './EmptyStates'

const meta: Meta = {
    title: 'Scenes-App/Insights/Loading Messages',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta

type Story = StoryObj<{}>

export const LoadingMessages: Story = {
    render: () => {
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
    },
}
