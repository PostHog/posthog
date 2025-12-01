import { useActions } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonInput, LemonSelect, LemonSwitch, LemonTable } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ChannelsTag } from '../../components/Channels/ChannelsTag'
import { ScenesTabs } from '../../components/ScenesTabs'
import type { TicketChannel } from '../../data/tickets'

type GuidancePack = {
    id: string
    title: string
    enabled: boolean
    channels: string[]
    rules: number
    updated: string
}

const guidancePacks: GuidancePack[] = [
    {
        id: 'guide-1',
        title: 'EU Compliance tone',
        enabled: true,
        channels: ['widget', 'email'],
        rules: 6,
        updated: '2d ago',
    },
    {
        id: 'guide-2',
        title: 'Escalation playbook · High ARR',
        enabled: true,
        channels: ['slack'],
        rules: 4,
        updated: '6h ago',
    },
    {
        id: 'guide-3',
        title: 'Billing empathy preset',
        enabled: false,
        channels: ['email'],
        rules: 3,
        updated: 'Today',
    },
]

export const scene: SceneExport = {
    component: ConversationsGuidanceScene,
}

export function ConversationsGuidanceScene(): JSX.Element {
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
                Control how the AI behaves. Set tone & style for communication personality, and define escalation rules
                for when to hand off to a human (legal mentions, high-value refunds, manager requests).
            </p>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap gap-2">
                    <LemonInput className="max-w-xs" placeholder="Search guidance" size="small" />
                    <LemonSelect
                        value="all"
                        options={[
                            { label: 'All', value: 'all' },
                            { label: 'Enabled', value: 'enabled' },
                            { label: 'Disabled', value: 'disabled' },
                        ]}
                        onChange={() => null}
                        placeholder="Status"
                        size="small"
                    />
                </div>
                <div>
                    <LemonButton type="primary">New guidance</LemonButton>
                </div>
            </div>
            <LemonTable
                dataSource={guidancePacks}
                rowKey="id"
                onRow={(entry) => ({
                    onClick: () => push(`/conversations/guidance/${entry.id}`),
                })}
                columns={[
                    {
                        title: 'Title',
                        dataIndex: 'title',
                    },
                    {
                        title: 'Channels',
                        key: 'channels',
                        render: (_, record) => (
                            <div className="flex gap-1 text-xs text-muted-alt">
                                {record.channels.map((channel) => (
                                    <ChannelsTag key={channel} channel={channel as TicketChannel} />
                                ))}
                            </div>
                        ),
                    },
                    {
                        title: 'Rules',
                        dataIndex: 'rules',
                    },
                    {
                        title: 'Updated',
                        dataIndex: 'updated',
                    },
                    {
                        title: 'Enabled',
                        key: 'enabled',
                        align: 'right',
                        render: (_, record) => (
                            <div className="flex justify-end">
                                <LemonSwitch checked={record.enabled} onChange={() => null} />
                            </div>
                        ),
                    },
                ]}
            />
        </SceneContent>
    )
}
