import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { NavPanelMcpAd } from './NavPanelMcpAd'

const meta = {
    title: 'Components/NavPanelMcpAd',
    parameters: { layout: 'padded' },
    decorators: [mswDecorator({ get: { '/api/oauth/connected-apps/': [] } })],
} satisfies Meta

export default meta
type Story = StoryObj<{}>

export const NotConnected: Story = {
    render: (): JSX.Element => (
        // The card renders inside the narrow sidebar, so mirror that width here.
        <div className="w-[232px]">
            <NavPanelMcpAd fallback={null} />
        </div>
    ),
    parameters: {
        testOptions: { waitForSelector: '[aria-label="Copy MCP install command"]' },
    },
}
