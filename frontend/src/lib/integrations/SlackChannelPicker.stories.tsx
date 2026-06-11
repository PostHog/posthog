import { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { useStorybookMocks } from '~/mocks/browser'
import { mockIntegration } from '~/test/mocks'
import { SlackChannelType } from '~/types'

import { recordRecentSlackChannel } from './slackChannel'
import { SlackChannelPicker } from './SlackIntegrationHelpers'
import { slackIntegrationLogic } from './slackIntegrationLogic'

const integration = mockIntegration

const channel = (id: string, name: string): SlackChannelType => ({
    id,
    name,
    is_private: false,
    is_ext_shared: false,
    is_member: true,
    is_private_without_access: false,
})

const channels: SlackChannelType[] = [
    channel('C1', 'alerts'),
    channel('C2', 'announcements'),
    channel('C3', 'deploys'),
    channel('C4', 'general'),
    channel('C5', 'incidents'),
    channel('C6', 'random'),
]

// `recentlySubscribedChannelIds` read top-to-bottom: index 0 is the most-recently subscribed.
function OrderingScene({ recentlySubscribedChannelIds }: { recentlySubscribedChannelIds: string[] }): JSX.Element {
    const logic = slackIntegrationLogic({ id: integration.id })
    const { slackChannelsForPicker } = useValues(logic)
    const { loadAllSlackChannels } = useActions(logic)

    useEffect(() => {
        window.localStorage.clear()
        // Record oldest first so the most-recent ends up at the front of the store.
        ;[...recentlySubscribedChannelIds].reverse().forEach((id) => recordRecentSlackChannel(integration.id, id))
        loadAllSlackChannels()
        return () => window.localStorage.clear()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    const recent = new Set(recentlySubscribedChannelIds)

    return (
        <div className="p-4 max-w-md deprecated-space-y-4">
            <div>
                <h4>Picker</h4>
                <SlackChannelPicker integration={integration} onChange={() => {}} />
            </div>
            <div>
                <h4>Order shown in the dropdown</h4>
                <ol className="deprecated-space-y-1 pl-4">
                    {slackChannelsForPicker.map((c) => (
                        <li key={c.id} className="flex items-center justify-between gap-2">
                            <span>#{c.name}</span>
                            {recent.has(c.id) ? <LemonTag type="highlight">recents</LemonTag> : null}
                        </li>
                    ))}
                </ol>
            </div>
        </div>
    )
}

type StoryArgs = { recentlySubscribedChannelIds: string[] }

const meta: Meta<StoryArgs> = {
    title: 'Components/Slack channel picker',
    parameters: { layout: 'fullscreen', viewMode: 'story' },
    render: ({ recentlySubscribedChannelIds }) => {
        useStorybookMocks({
            get: {
                '/api/projects/:id/integrations/:intId/channels': { channels },
                '/api/environments/:id/integrations/:intId/channels': { channels },
            },
        })
        return <OrderingScene recentlySubscribedChannelIds={recentlySubscribedChannelIds} />
    },
}
export default meta

type Story = StoryObj<StoryArgs>

// No recency recorded yet — channels fall back to plain alphabetical order.
export const Alphabetical: Story = {
    args: { recentlySubscribedChannelIds: [] },
}

// "general" then "alerts" were the last two channels subscribed, so they float to the top
// (most recent first); everything else stays alphabetical below them.
export const RecentlySubscribedFirst: Story = {
    args: { recentlySubscribedChannelIds: ['C4', 'C1'] },
}
