import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { NAV_PANEL_PLACEMENT } from './navPanelAdShared'
import { NavPanelMcpAd } from './NavPanelMcpAd'

const meta = {
    title: 'Components/NavPanelMcpAd',
    parameters: { layout: 'padded' },
    decorators: [mswDecorator({ get: { '/api/oauth/connected-apps/': [] } })],
} satisfies Meta

export default meta
type Story = StoryObj<{}>

// The card's width in the sidebar at its default width (215px) and at its minimum (160px).
const notConnectedStory = (width: string): Story => ({
    render: (): JSX.Element => (
        <div className={width}>
            <NavPanelMcpAd placement={NAV_PANEL_PLACEMENT.SIDEBAR} />
        </div>
    ),
    parameters: {
        testOptions: { waitForSelector: '[aria-label="Copy MCP install command"]' },
    },
})

export const NotConnected: Story = notConnectedStory('w-[199px]')

export const NotConnectedNarrowSidebar: Story = notConnectedStory('w-[144px]')
