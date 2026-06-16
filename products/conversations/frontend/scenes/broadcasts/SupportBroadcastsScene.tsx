import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonInputSelect,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { stripMarkdown } from 'lib/utils/stripMarkdown'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { ScenesTabs } from '../../components/ScenesTabs'
import type { BroadcastApi, BroadcastDeliveryApi } from '../../generated/api.schemas'
import { broadcastsLogic } from './broadcastsLogic'

export const scene: SceneExport = {
    component: SupportBroadcastsScene,
    logic: broadcastsLogic,
    productKey: ProductKey.CONVERSATIONS,
}

type TagType = 'success' | 'primary' | 'warning' | 'danger' | 'default'

function broadcastStatusTag(status: BroadcastApi['status']): { type: TagType; label: string } {
    switch (status) {
        case 'sent':
            return { type: 'success', label: 'Sent' }
        case 'sending':
            return { type: 'primary', label: 'Sending' }
        case 'partially_failed':
            return { type: 'warning', label: 'Partially failed' }
        case 'failed':
            return { type: 'danger', label: 'Failed' }
        default:
            return { type: 'default', label: 'Pending' }
    }
}

function BroadcastComposer(): JSX.Element {
    const {
        messageDraft,
        selectedChannelIds,
        memberChannels,
        memberChannelsLoading,
        submitting,
        submitDisabledReason,
    } = useValues(broadcastsLogic)
    const { setMessage, setSelectedChannelIds, submitBroadcast, loadMemberChannels } = useActions(broadcastsLogic)

    return (
        <div className="flex flex-col gap-2 max-w-[800px]">
            <LemonTextArea
                value={messageDraft}
                onChange={setMessage}
                placeholder="Write a message to broadcast to the selected channels…"
                minRows={4}
            />
            <div className="flex gap-2 items-center">
                <LemonInputSelect
                    mode="multiple"
                    value={selectedChannelIds}
                    options={memberChannels.map((channel) => ({ key: channel.id, label: `#${channel.name}` }))}
                    onChange={setSelectedChannelIds}
                    loading={memberChannelsLoading}
                    placeholder="Select channels the SupportHog bot is in"
                    className="flex-1"
                />
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={loadMemberChannels}
                    disabledReason={memberChannelsLoading ? 'Loading channels…' : undefined}
                >
                    Refresh
                </LemonButton>
            </div>
            <div>
                <LemonButton
                    type="primary"
                    onClick={submitBroadcast}
                    loading={submitting}
                    disabledReason={submitDisabledReason}
                >
                    Send broadcast
                </LemonButton>
            </div>
        </div>
    )
}

function DeliveriesTable({ deliveries }: { deliveries: readonly BroadcastDeliveryApi[] }): JSX.Element {
    const columns: LemonTableColumns<BroadcastDeliveryApi> = [
        {
            title: 'Channel',
            key: 'channel',
            render: (_, delivery) =>
                delivery.slack_channel_name ? `#${delivery.slack_channel_name}` : delivery.slack_channel_id,
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, delivery) => (
                <LemonTag
                    type={delivery.status === 'sent' ? 'success' : delivery.status === 'failed' ? 'danger' : 'default'}
                >
                    {delivery.status}
                </LemonTag>
            ),
        },
        {
            title: 'Error',
            key: 'error',
            render: (_, delivery) =>
                delivery.error ? <span className="text-danger text-xs">{delivery.error}</span> : '—',
        },
    ]
    return <LemonTable embedded dataSource={[...deliveries]} rowKey="id" columns={columns} />
}

function BroadcastHistory(): JSX.Element {
    const { broadcasts, broadcastsLoading } = useValues(broadcastsLogic)
    const { loadBroadcasts } = useActions(broadcastsLogic)

    const columns: LemonTableColumns<BroadcastApi> = [
        {
            title: 'Message',
            key: 'message',
            render: (_, broadcast) => (
                <span className="truncate max-w-md inline-block">{stripMarkdown(broadcast.message)}</span>
            ),
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, broadcast) => {
                const tag = broadcastStatusTag(broadcast.status)
                return <LemonTag type={tag.type}>{tag.label}</LemonTag>
            },
        },
        {
            title: 'Delivered',
            key: 'sent_count',
            render: (_, broadcast) => `${broadcast.sent_count}/${broadcast.total_channels}`,
        },
        {
            title: 'Failed',
            key: 'failed_count',
            render: (_, broadcast) => broadcast.failed_count || '—',
        },
        {
            title: 'Created',
            key: 'created_at',
            render: (_, broadcast) => <TZLabel time={broadcast.created_at} />,
        },
        {
            title: 'By',
            key: 'created_by',
            render: (_, broadcast) => broadcast.created_by?.first_name || broadcast.created_by?.email || '—',
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
                <h3 className="m-0">Sent broadcasts</h3>
                <LemonButton type="secondary" size="small" onClick={loadBroadcasts} loading={broadcastsLoading}>
                    Refresh
                </LemonButton>
            </div>
            <LemonTable<BroadcastApi>
                dataSource={broadcasts}
                loading={broadcastsLoading}
                rowKey="id"
                columns={columns}
                expandable={{
                    expandedRowRender: (broadcast) => <DeliveriesTable deliveries={broadcast.deliveries} />,
                    rowExpandable: (broadcast) => broadcast.deliveries.length > 0,
                }}
                emptyState="No broadcasts sent yet"
            />
        </div>
    )
}

export function SupportBroadcastsScene(): JSX.Element {
    const { slackEnabled } = useValues(broadcastsLogic)

    return (
        <SceneContent className="pb-4">
            <SceneTitleSection name="Support" description="" resourceType={{ type: 'conversation' }} />
            <ScenesTabs />
            {slackEnabled ? (
                <div className="flex flex-col gap-6">
                    <BroadcastComposer />
                    <BroadcastHistory />
                </div>
            ) : (
                <LemonBanner type="warning">
                    Connect the SupportHog Slack bot in <Link to={urls.supportSettings()}>Support settings</Link> to
                    send broadcasts.
                </LemonBanner>
            )}
        </SceneContent>
    )
}
