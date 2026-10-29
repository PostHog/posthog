import { MOCK_DEFAULT_USER, MOCK_TEAM_ID } from 'lib/api.mock'

import './__mocks__/fakeExtensionBrowser'

import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import type { PageToolbarMode } from '../../messaging/pageToolbarBridge'
import { configureFakeExtensionBrowser } from './__mocks__/fakeExtensionBrowser'
import { STORY_PAGE_URL, pageToolbarState } from './__mocks__/pageToolbarState'
import { ExtensionPanel } from './ExtensionPanel'

type StoryArgs = { mode: PageToolbarMode }

const meta: Meta<StoryArgs> = {
    title: 'Scenes-Other/Toolbar extension',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-01-15 10:01:00',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/users/@me/': MOCK_DEFAULT_USER,
                '/api/user/toolbar_entitlements': { entitlements: { toolbar_heatmaps: true } },
                '/api/organizations/:organization_id/projects/:id/': {
                    app_urls: ['https://hedgebox.example.com'],
                    data_attributes: ['data-attr'],
                },
            },
        }),
    ],
    render: ({ mode }) => {
        const uiHost = window.location.origin
        configureFakeExtensionBrowser({
            tabUrl: STORY_PAGE_URL,
            pageState: pageToolbarState(mode),
            storage: {
                posthogUiHost: uiHost,
                posthogToolbarTokens: {
                    [`${uiHost}|${MOCK_TEAM_ID}`]: { accessToken: 'pha_story', refreshToken: null, clientId: 'story' },
                },
            },
        })
        // The width of the Chrome side panel when it opens.
        return (
            <div className="w-[360px] border-r">
                <ExtensionPanel />
            </div>
        )
    },
}
export default meta

type Story = StoryObj<StoryArgs>

export const Home: Story = {
    args: { mode: 'none' },
    parameters: { testOptions: { waitForSelector: 'text=Hover a tool to see what it does' } },
}

export const Inspect: Story = {
    args: { mode: 'inspect' },
    parameters: { testOptions: { waitForSelector: 'text=Started trial' } },
}

export const Heatmap: Story = {
    args: { mode: 'heatmap' },
    parameters: { testOptions: { waitForSelector: 'text=Compare plans' } },
}

export const Actions: Story = {
    args: { mode: 'actions' },
    parameters: { testOptions: { waitForSelector: 'text=Clicked contact sales' } },
}

export const FeatureFlags: Story = {
    args: { mode: 'flags' },
    parameters: { testOptions: { waitForSelector: 'text=checkout-button-copy' } },
}

export const Events: Story = {
    args: { mode: 'events' },
    parameters: { testOptions: { waitForSelector: 'text=trial started' } },
}

export const WebVitals: Story = {
    args: { mode: 'web-vitals' },
    parameters: { testOptions: { waitForSelector: 'text=1.64s' } },
}

export const Experiments: Story = {
    args: { mode: 'experiments' },
    parameters: { testOptions: { waitForSelector: 'text=Trial button color' } },
}

export const More: Story = {
    args: { mode: 'more' },
    parameters: { testOptions: { waitForSelector: 'text=1.300.0' } },
}
