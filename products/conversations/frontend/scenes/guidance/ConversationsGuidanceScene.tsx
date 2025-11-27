import {
    LemonButton,
    LemonCard,
    LemonInput,
    LemonSelect,
    LemonSwitch,
    LemonTable,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ScenesTabs } from '../../components/ScenesTabs'

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

const tonePresets = [
    { label: 'Professional', value: 'professional' },
    { label: 'Friendly', value: 'friendly' },
    { label: 'Empathetic', value: 'empathetic' },
]

const escalationRules = [
    { trigger: 'ARR ≥ $200k AND sentiment ≤ -0.5', destination: 'Enterprise manager' },
    { trigger: 'Policy mismatch mention', destination: 'Legal queue' },
    { trigger: 'Widget errors × 3 in 5m', destination: 'Support engineer' },
]

export const scene: SceneExport = {
    component: ConversationsGuidanceScene,
}

export function ConversationsGuidanceScene(): JSX.Element {
    return (
        <SceneContent className="space-y-5">
            <ScenesTabs />
            <section className="flex flex-wrap items-center justify-between gap-2">
                <div>
                    <h1 className="text-2xl font-semibold">Guidance & guardrails</h1>
                    <p className="text-muted-alt">
                        Control tone, escalation rules, and rollouts so AI responses follow policy.
                    </p>
                </div>
                <div className="flex gap-2">
                    <LemonButton type="secondary">Import guidance</LemonButton>
                    <LemonButton type="primary">New guidance pack</LemonButton>
                </div>
            </section>

            <div className="grid gap-4 lg:grid-cols-3">
                <LemonCard hoverEffect={false}>
                    <div className="text-sm text-muted-alt">Active packs</div>
                    <div className="text-3xl font-semibold">12</div>
                    <div className="text-xs text-success mt-1">+2 this week</div>
                </LemonCard>
                <LemonCard hoverEffect={false}>
                    <div className="text-sm text-muted-alt">Escalation rules</div>
                    <div className="text-3xl font-semibold">28</div>
                    <div className="text-xs text-muted-alt">8 include auto handoff</div>
                </LemonCard>
                <LemonCard hoverEffect={false}>
                    <div className="text-sm text-muted-alt">Channels covered</div>
                    <div className="text-3xl font-semibold">3</div>
                    <div className="text-xs text-muted-alt">Widget · Slack · Email</div>
                </LemonCard>
            </div>

            <LemonCard hoverEffect={false}>
                <div className="mb-3 flex flex-wrap items-center gap-2">
                    <LemonInput className="max-w-xs" placeholder="Search guidance" />
                    <LemonSelect
                        value="all"
                        options={[
                            { label: 'All statuses', value: 'all' },
                            { label: 'Active', value: 'active' },
                            { label: 'Draft', value: 'draft' },
                        ]}
                        onChange={() => null}
                        placeholder="Status"
                    />
                    <LemonSelect
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
                                        <LemonTag key={channel} size="small" type="muted">
                                            {channel}
                                        </LemonTag>
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
                                <LemonSwitch checked={record.status === 'active'} onChange={() => null} />
                            ),
                        },
                    ]}
                />
            </LemonCard>

            <div className="grid gap-4 lg:grid-cols-2">
                <LemonCard hoverEffect={false}>
                    <h3 className="text-lg font-semibold">Tone guidance</h3>
                    <p className="text-sm text-muted-alt">Set guardrails for voice, empathy, and prohibited phrases.</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                        <LemonSelect
                            className="min-w-[200px]"
                            value="professional"
                            options={tonePresets}
                            onChange={() => null}
                            placeholder="Tone preset"
                        />
                        <LemonInput className="flex-1" placeholder="Add prohibited phrase" />
                    </div>
                    <LemonTextArea className="mt-3" minRows={4} placeholder="Tone instructions" />
                    <div className="mt-3 flex gap-2">
                        <LemonButton type="secondary">Preview voice</LemonButton>
                        <LemonButton type="primary">Save tone</LemonButton>
                    </div>
                </LemonCard>

                <LemonCard hoverEffect={false}>
                    <h3 className="text-lg font-semibold">Escalation triggers</h3>
                    <p className="text-sm text-muted-alt">Define when AI must hand off to humans.</p>
                    <LemonTable
                        className="mt-3"
                        dataSource={escalationRules}
                        rowKey="trigger"
                        columns={[
                            { title: 'Trigger', dataIndex: 'trigger' },
                            { title: 'Destination', dataIndex: 'destination' },
                            {
                                title: '',
                                key: 'actions',
                                align: 'right',
                                render: () => <LemonButton size="small">Edit</LemonButton>,
                            },
                        ]}
                    />
                    <LemonButton className="mt-3" type="secondary">
                        Manage triggers
                    </LemonButton>
                </LemonCard>
            </div>
        </SceneContent>
    )
}
