import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonInputSelect,
    LemonSnack,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type { ShoutoutApi, ShoutoutDeliveryApi } from '../../generated/api.schemas'
import { ShoutoutAccountFilters } from './ShoutoutAccountFilters'
import { shoutoutsLogic } from './shoutoutsLogic'

type TagType = 'success' | 'primary' | 'warning' | 'danger' | 'default'

function shoutoutStatusTag(status: ShoutoutApi['status']): { type: TagType; label: string } {
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

function ConfirmSendContent({ message, channelLabels }: { message: string; channelLabels: string[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-2 max-w-[500px]">
            <p className="m-0">
                This message will be posted to {pluralize(channelLabels.length, 'customer channel')}. Sending cannot be
                undone.
            </p>
            <div className="border rounded p-2 bg-surface-secondary whitespace-pre-wrap max-h-40 overflow-y-auto">
                {message}
            </div>
            <div className="flex flex-wrap gap-1 max-h-32 overflow-y-auto">
                {channelLabels.map((label) => (
                    <LemonSnack key={label}>{label}</LemonSnack>
                ))}
            </div>
        </div>
    )
}

function ShoutoutComposer(): JSX.Element {
    const {
        messageDraft,
        selectedChannelIds,
        selectedChannelLabels,
        channelOptions,
        memberChannelsLoading,
        submitting,
        submitDisabledReason,
    } = useValues(shoutoutsLogic)
    const { setMessage, setSelectedChannelIds, submitShoutout, loadMemberChannels } = useActions(shoutoutsLogic)

    const confirmSend = (): void => {
        LemonDialog.open({
            title: `Send this shoutout to ${pluralize(selectedChannelLabels.length, 'channel')}?`,
            content: <ConfirmSendContent message={messageDraft.trim()} channelLabels={selectedChannelLabels} />,
            primaryButton: {
                children: 'Send',
                onClick: submitShoutout,
                'data-attr': 'confirm-send-shoutout',
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    return (
        <div className="flex flex-col gap-2 max-w-[800px]">
            <LemonTextArea
                value={messageDraft}
                onChange={setMessage}
                placeholder="Write a message to send to the selected customer channels…"
                minRows={4}
            />
            <ShoutoutAccountFilters />
            <div className="flex gap-2 items-center">
                <LemonInputSelect
                    mode="multiple"
                    value={selectedChannelIds}
                    options={channelOptions}
                    onChange={setSelectedChannelIds}
                    loading={memberChannelsLoading}
                    placeholder="Select customer channels"
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
                    onClick={confirmSend}
                    loading={submitting}
                    disabledReason={submitDisabledReason}
                    data-attr="send-shoutout"
                >
                    Send shoutout
                </LemonButton>
            </div>
        </div>
    )
}

function DeliveriesTable({ deliveries }: { deliveries: readonly ShoutoutDeliveryApi[] }): JSX.Element {
    const columns: LemonTableColumns<ShoutoutDeliveryApi> = [
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

function ShoutoutHistory(): JSX.Element {
    const { shoutouts, shoutoutsLoading } = useValues(shoutoutsLogic)
    const { loadShoutouts } = useActions(shoutoutsLogic)

    const columns: LemonTableColumns<ShoutoutApi> = [
        {
            title: 'Message',
            key: 'message',
            render: (_, shoutout) => <span className="truncate max-w-md inline-block">{shoutout.message}</span>,
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, shoutout) => {
                const tag = shoutoutStatusTag(shoutout.status)
                return <LemonTag type={tag.type}>{tag.label}</LemonTag>
            },
        },
        {
            title: 'Delivered',
            key: 'sent_count',
            render: (_, shoutout) => `${shoutout.sent_count}/${shoutout.total_channels}`,
        },
        {
            title: 'Failed',
            key: 'failed_count',
            render: (_, shoutout) => shoutout.failed_count || '—',
        },
        {
            title: 'Created',
            key: 'created_at',
            render: (_, shoutout) => <TZLabel time={shoutout.created_at} />,
        },
        {
            title: 'By',
            key: 'created_by',
            render: (_, shoutout) => shoutout.created_by?.first_name || shoutout.created_by?.email || '—',
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
                <h3 className="m-0">Sent shoutouts</h3>
                <LemonButton type="secondary" size="small" onClick={loadShoutouts} loading={shoutoutsLoading}>
                    Refresh
                </LemonButton>
            </div>
            <LemonTable<ShoutoutApi>
                dataSource={shoutouts}
                loading={shoutoutsLoading}
                rowKey="id"
                columns={columns}
                expandable={{
                    expandedRowRender: (shoutout) => <DeliveriesTable deliveries={shoutout.deliveries} />,
                    rowExpandable: (shoutout) => shoutout.deliveries.length > 0,
                }}
                emptyState="No shoutouts sent yet"
            />
        </div>
    )
}

export function ShoutoutsTabContent(): JSX.Element {
    const { slackConnected } = useValues(shoutoutsLogic)

    if (!slackConnected) {
        return (
            <LemonBanner type="warning">
                Connect the SupportHog Slack bot in <Link to={urls.supportSettings()}>Support settings</Link> to send
                shoutouts to customer channels.
            </LemonBanner>
        )
    }

    return (
        <div className="flex flex-col gap-6">
            <ShoutoutComposer />
            <ShoutoutHistory />
        </div>
    )
}
