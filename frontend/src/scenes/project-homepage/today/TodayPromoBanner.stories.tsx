import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { TodayBroadcastBanner } from './TodayBroadcastBanner'
import { TodayMcpBanner } from './TodayMcpBanner'

const meta = {
    title: 'Scenes-App/Today/Promo banner',
    parameters: {
        layout: 'padded',
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        (Story) => (
            <div data-quill className="max-w-[720px]">
                <Story />
            </div>
        ),
    ],
} satisfies Meta

export default meta
type Story = StoryObj<{}>

export const Broadcast: Story = {
    render: () => (
        <TodayBroadcastBanner
            broadcast={{
                broadcast: 'storybook-broadcast',
                title: 'Managed warehouse is in beta',
                text: 'Query your events and your connected sources in one place, with no warehouse of your own to run.',
                emoji: '🏠',
                emojiLabel: 'house',
            }}
        />
    ),
}

export const McpConnect: Story = {
    decorators: [mswDecorator({ get: { '/api/oauth/connected-apps/': [] } })],
    render: () => <TodayMcpBanner />,
    parameters: { testOptions: { waitForSelector: '[aria-label="Copy MCP install command"]' } },
}
