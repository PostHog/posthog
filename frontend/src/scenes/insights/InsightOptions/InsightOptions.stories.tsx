import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Insights/Insight Options',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
        pageUrl: urls.insightOptions(),
    },
    decorators: [mswDecorator({})],
}
export default meta

type Story = StoryObj<typeof meta>
export const Default: Story = {}
