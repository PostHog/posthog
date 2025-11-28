import { LemonButton, LemonInput, LemonSelect, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ChannelsTag } from '../../components/Channels/ChannelsTag'
import { ScenesTabs } from '../../components/ScenesTabs'
import type { TicketChannel } from '../../data/tickets'

type GuidancePack = {
    id: string
    title: string
    status: 'active' | 'draft'
    channels: string[]
    rules: number
    updated: string
}

const guidancePacks: GuidancePack[] = [
    {
        id: 'guide-1',
        title: 'EU Compliance tone',
        status: 'active',
        channels: ['widget', 'email'],
        rules: 6,
        updated: '2d ago',
    },
    {
        id: 'guide-2',
        title: 'Escalation playbook · High ARR',
        status: 'active',
        channels: ['slack'],
        rules: 4,
        updated: '6h ago',
    },
    {
        id: 'guide-3',
        title: 'Billing empathy preset',
        status: 'draft',
        channels: ['email'],
        rules: 3,
        updated: 'Today',
    },
]

export const scene: SceneExport = {
    component: ConversationsGuidanceScene,
}

export function ConversationsGuidanceScene(): JSX.Element {
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
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap gap-2">
                    <LemonInput className="max-w-xs" placeholder="Search guidance" size="small" />
                    <LemonSelect
                        value="all"
                        options={[
                            { label: 'All statuses', value: 'all' },
                            { label: 'Active', value: 'active' },
                            { label: 'Draft', value: 'draft' },
                        ]}
                        onChange={() => null}
                        placeholder="Status"
                        size="small"
                    />
                    <LemonSelect
                        size="small"
                        className="min-w-[200px]"
                        placeholder="Channel"
                        value={null}
                        options={[
                            { label: 'All channels', value: null },
                            { label: 'Widget', value: 'widget' },
                            { label: 'Slack', value: 'slack' },
                            { label: 'Email', value: 'email' },
                        ]}
                        onChange={() => null}
                    />
                </div>
                <div>
                    <LemonButton type="secondary" size="small">
                        New guidance
                    </LemonButton>
                </div>
            </div>
            <LemonTable
                dataSource={guidancePacks}
                rowKey="id"
                columns={[
                    {
                        title: 'Title',
                        dataIndex: 'title',
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        render: (_, record) => (
                            <LemonTag type={record.status === 'active' ? 'success' : 'default'}>
                                {record.status}
                            </LemonTag>
                        ),
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
                        title: 'Auto handoff',
                        key: 'handoff',
                        align: 'right',
                        render: (_, record) => (
                            <>
                                {record.status === 'active' ? (
                                    <LemonTag type="success">Yes</LemonTag>
                                ) : (
                                    <LemonTag type="default">No</LemonTag>
                                )}
                            </>
                        ),
                    },
                ]}
            />
        </SceneContent>
    )
}
