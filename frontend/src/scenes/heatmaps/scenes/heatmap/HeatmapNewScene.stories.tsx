import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Heatmap New',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        pageUrl: urls.heatmapNew ? urls.heatmapNew() : urls.heatmap('new'),
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [mswDecorator({})],
}
export default meta

type Story = StoryObj<typeof meta>

export const NewForm: Story = {}
