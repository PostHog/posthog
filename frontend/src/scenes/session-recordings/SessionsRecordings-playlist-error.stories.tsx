import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { ReplayTabs } from '~/types'

const meta: Meta = {
    component: App,
    title: 'Replay/Tabs/Recordings',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.replay(ReplayTabs.Home),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/session_recordings': () => [
                    500,
                    { detail: 'Query exceeded the memory limit. Try a shorter date range.' },
                ],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const RecordingsListFailed: Story = {}
