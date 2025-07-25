import { Meta, StoryObj } from '@storybook/react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Comments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
        pageUrl: urls.comments(),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/comments/': {},
                '/api/projects/:team_id/comments/:commentId/': () => [200, []],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>
export const Comments: Story = {}
