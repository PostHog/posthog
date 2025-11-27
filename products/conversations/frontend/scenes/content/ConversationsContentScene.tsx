import { useActions } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonSelect, LemonSwitch, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ScenesTabs } from '../../components/ScenesTabs'

const contentTypes = [
    { value: 'procedures', label: 'Procedures' },
    { value: 'articles', label: 'Articles' },
    { value: 'snippets', label: 'Snippets' },
]

const contentEntries = [
    {
        id: 'cnt-001',
        title: 'Cloudflare allowlist procedure',
        type: 'Procedure',
        targeting: 'Region = EU',
        channels: ['widget', 'slack'],
        status: 'published',
        updated: '2h ago',
    },
    {
        id: 'cnt-002',
        title: 'Refund policy escalation rules',
        type: 'Procedure',
        targeting: 'Plan = Enterprise',
        channels: ['widget'],
        status: 'published',
        updated: 'Yesterday',
    },
    {
        id: 'cnt-003',
        title: 'Chargeback snippet',
        type: 'Snippet',
        targeting: 'Segment = High ARR',
        channels: ['email'],
        status: 'draft',
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

            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap gap-2">
                    <LemonSelect value="procedures" options={contentTypes} placeholder="Content type" size="small" />
                    <LemonSelect
                        value="all"
                        options={[
                            { value: 'all', label: 'All statuses' },
                            { value: 'draft', label: 'Draft' },
                            { value: 'published', label: 'Published' },
                        ]}
                        placeholder="Status"
                        size="small"
                    />
                    <LemonSelect
                        value="audience"
                        options={[
                            { value: 'audience', label: 'Audience' },
                            { value: 'geo', label: 'Geo' },
                            { value: 'plan', label: 'Plan' },
                        ]}
                        placeholder="Audience"
                        size="small"
                    />
                </div>
                <div className="flex flex-wrap gap-2">
                    <LemonButton type="secondary">Import CSV</LemonButton>
                    <LemonButton type="primary">New content</LemonButton>
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
                            key: 'title',
                            render: (_, entry) => (
                                <div>
                                    <div className="font-medium">{entry.title}</div>
                                    <div className="text-xs text-muted-alt">{entry.targeting}</div>
                                </div>
                            ),
                        },
                        {
                            title: 'Type',
                            dataIndex: 'type',
                        },
                        {
                            title: 'Channels',
                            key: 'channels',
                            render: (_, entry) => (
                                <div className="flex gap-1 text-xs text-muted-alt">
                                    {entry.channels.map((channel) => (
                                        <LemonTag key={channel} size="small" type="muted">
                                            {channel}
                                        </LemonTag>
                                    ))}
                                </div>
                            ),
                        },
                        {
                            title: 'Status',
                            key: 'status',
                            render: (_, entry) => (
                                <LemonTag type={entry.status === 'published' ? 'success' : 'default'}>
                                    {entry.status}
                                </LemonTag>
                            ),
                        },
                        {
                            title: 'Updated',
                            dataIndex: 'updated',
                        },
                        {
                            title: 'Toggle',
                            key: 'toggle',
                            align: 'right',
                            render: (_, entry) => (
                                <LemonSwitch checked={entry.status === 'published'} onChange={() => null} />
                            ),
                        },
                    ]}
                />
            </div>
        </SceneContent>
    )
}
