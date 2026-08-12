import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonCollapse,
    LemonInput,
    LemonLabel,
    LemonSkeleton,
    LemonTag,
} from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { EmailForwardingAddress } from 'products/conversations/frontend/components/EmailForwardingAddress'

import { customerEmailConfigLogic } from './customerEmailConfigLogic'
import type { CustomerEmailChannel } from './customerEmailConfigLogic'

function ConnectedEmailContent({ channel }: { channel: CustomerEmailChannel }): JSX.Element {
    const { disconnectingChannelId } = useValues(customerEmailConfigLogic)
    const { disconnectEmail } = useActions(customerEmailConfigLogic)

    return (
        <div className="flex flex-col gap-3 p-3">
            {channel.forwarding_address ? (
                <EmailForwardingAddress forwardingAddress={channel.forwarding_address} />
            ) : (
                <p className="mb-0 text-sm text-secondary">
                    A forwarding address is not available. Ask your PostHog administrator to configure the inbound email
                    domain.
                </p>
            )}
            <div className="flex justify-end border-t pt-2">
                <LemonButton
                    type="secondary"
                    status="danger"
                    size="small"
                    icon={<IconTrash />}
                    loading={disconnectingChannelId === channel.id}
                    disabledReason={disconnectingChannelId ? 'Another email is being disconnected' : undefined}
                    onClick={() => {
                        LemonDialog.open({
                            title: `Disconnect ${channel.from_email}?`,
                            description: 'New messages sent to this email will stop appearing on customer accounts.',
                            primaryButton: {
                                children: 'Disconnect',
                                status: 'danger',
                                onClick: () => disconnectEmail(channel.id),
                            },
                            secondaryButton: { children: 'Cancel' },
                        })
                    }}
                >
                    Disconnect
                </LemonButton>
            </div>
        </div>
    )
}

function connectedEmailHeader(channel: CustomerEmailChannel): JSX.Element {
    return (
        <div className="flex min-w-0 items-center gap-2 text-left">
            <span className="truncate font-medium">{channel.from_email}</span>
            <LemonTag type="success" size="small" className="shrink-0">
                Connected
            </LemonTag>
        </div>
    )
}

function AddEmailForm(): JSX.Element {
    const { addEmailFormVisible, connecting, emailDraft } = useValues(customerEmailConfigLogic)
    const { connectEmail, setAddEmailFormVisible, setEmailDraft } = useActions(customerEmailConfigLogic)

    if (!addEmailFormVisible) {
        return (
            <LemonButton type="secondary" size="small" icon={<IconPlus />} onClick={() => setAddEmailFormVisible(true)}>
                Add email address
            </LemonButton>
        )
    }

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-2 px-4 py-3">
            <LemonLabel>Connect new email</LemonLabel>
            <p className="mb-0 text-sm text-secondary">
                Enter the email address you use to talk to customers. After connecting it, forward incoming messages to
                the PostHog address shown here.
            </p>
            <LemonInput
                type="email"
                value={emailDraft}
                onChange={setEmailDraft}
                placeholder="you@company.com"
                fullWidth
                disabled={connecting}
                onPressEnter={connectEmail}
            />
            <div className="flex gap-2">
                <LemonButton
                    type="primary"
                    size="small"
                    loading={connecting}
                    disabledReason={emailDraft.trim() ? undefined : 'Enter your email address'}
                    onClick={connectEmail}
                >
                    Connect email
                </LemonButton>
                <LemonButton
                    type="secondary"
                    size="small"
                    disabled={connecting}
                    onClick={() => setAddEmailFormVisible(false)}
                >
                    Cancel
                </LemonButton>
            </div>
        </LemonCard>
    )
}

export function CustomerEmailConfig(): JSX.Element {
    const { channels, channelsLoadFailed, channelsLoading, expandedChannelIds } = useValues(customerEmailConfigLogic)
    const { loadChannels, setExpandedChannelIds } = useActions(customerEmailConfigLogic)

    if (channelsLoading) {
        return <LemonSkeleton className="h-32 max-w-2xl" />
    }
    if (channelsLoadFailed) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: loadChannels }}>
                Could not load your connected emails.
            </LemonBanner>
        )
    }

    return (
        <div className="flex max-w-2xl flex-col gap-3">
            {channels.length > 0 && (
                <LemonCollapse
                    className="bg-surface-primary"
                    multiple
                    activeKeys={expandedChannelIds}
                    onChange={setExpandedChannelIds}
                    panels={channels.map((channel) => ({
                        key: channel.id,
                        header: connectedEmailHeader(channel),
                        content: <ConnectedEmailContent channel={channel} />,
                    }))}
                />
            )}
            <div className="flex">
                <AddEmailForm />
            </div>
        </div>
    )
}
