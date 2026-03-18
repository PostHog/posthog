import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/People/Groups',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-07-04',
    },
}
export default meta

type Story = StoryObj<typeof meta>

export const Groups: Story = { parameters: { pageUrl: urls.groups(0) } }
