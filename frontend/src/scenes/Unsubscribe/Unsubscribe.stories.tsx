import { Meta, StoryObj } from '@storybook/react'

import { Unsubscribe } from './Unsubscribe'

const meta: Meta = {
    title: 'Scenes-Other/Unsubscribe',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta

type Story = StoryObj<{}>

export const UnsubscribeScene: Story = {
    render: () => <Unsubscribe />,
}
