import { useActions } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonSelect, LemonSwitch, LemonTable } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ChannelsTag } from '../../components/Channels/ChannelsTag'
import { ScenesTabs } from '../../components/ScenesTabs'
import type { TicketChannel } from '../../data/tickets'

const contentEntries = [
    {
        id: 'cnt-001',
        title: 'Widget connection troubleshooting',
        channels: ['widget', 'slack'],
        enabled: true,
        updated: '2h ago',
    },
    {
        id: 'cnt-002',
        title: 'Refund policy overview',
        channels: ['widget'],
        enabled: true,
        updated: 'Yesterday',
    },
    {
        id: 'cnt-003',
        title: 'Billing inquiry response',
        channels: ['email'],
        enabled: false,
        updated: 'Today',
    },
]

export const scene: SceneExport = {
    component: ConversationsContentScene,
}

export function ConversationsContentScene(): JSX.Element {
    const { push } = useActions(router)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Conversations"
                description=""
                resourceType={{
                    type: 'conversation',
                }}
            />
            <ScenesTabs />
            <p className="text-muted-alt mb-4">
                Knowledge base articles that the AI reads and synthesizes from. Add facts, features, and troubleshooting
                info that the AI can reference when responding to customers.
            </p>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap gap-2">
                    <LemonSelect
                        value="all"
                        options={[
                            { value: 'all', label: 'All' },
                            { value: 'enabled', label: 'Enabled' },
                            { value: 'disabled', label: 'Disabled' },
                        ]}
                        placeholder="Status"
                        size="small"
                    />
                </div>
                <div className="flex flex-wrap gap-2">
                    <LemonButton type="primary">New article</LemonButton>
                </div>
            </div>

            <div className="mt-4">
                <LemonTable
                    dataSource={contentEntries}
                    rowKey="id"
                    onRow={(entry) => ({
                        onClick: () => push(`/conversations/content/${entry.id}`),
                    })}
                    columns={[
                        {
                            title: 'Title',
                            dataIndex: 'title',
                        },
                        {
                            title: 'Channels',
                            key: 'channels',
                            render: (_, entry) => (
                                <div className="flex gap-1 text-xs text-muted-alt">
                                    {entry.channels.map((channel) => (
                                        <ChannelsTag key={channel} channel={channel as TicketChannel} />
                                    ))}
                                </div>
                            ),
                        },
                        {
                            title: 'Updated',
                            dataIndex: 'updated',
                        },
                        {
                            title: 'Enabled',
                            key: 'enabled',
                            align: 'right',
                            render: (_, entry) => (
                                <div className="flex justify-end">
                                    <LemonSwitch checked={entry.enabled} onChange={() => null} />
                                </div>
                            ),
                        },
                    ]}
                />
            </div>
        </SceneContent>
    )
}
