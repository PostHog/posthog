import { useActions, useValues } from 'kea'

import { IconCopy, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonInput, LemonLabel, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { customerEmailConfigLogic } from './customerEmailConfigLogic'
import type { CustomerEmailChannel } from './customerEmailConfigLogic'

function ConnectedEmail({ channel }: { channel: CustomerEmailChannel }): JSX.Element {
    const { disconnectingChannelId } = useValues(customerEmailConfigLogic)
    const { disconnectEmail } = useActions(customerEmailConfigLogic)

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                    <span className="font-medium">{channel.from_email}</span>
                    <LemonTag type="success" size="small">
                        Connected
                    </LemonTag>
                </div>
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
            {channel.forwarding_address ? (
                <div className="flex flex-col gap-1">
                    <LemonLabel>Forward incoming email to</LemonLabel>
                    <p className="mb-1 text-sm text-secondary">
                        Add this as a forwarding address in your email provider. Forwarded messages appear on matching
                        customer accounts.
                    </p>
                    <div className="flex items-center gap-2">
                        <code className="break-all rounded bg-surface-primary px-2 py-1 text-sm">
                            {channel.forwarding_address}
                        </code>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconCopy />}
                            tooltip="Copy forwarding address"
                            onClick={() => {
                                void navigator.clipboard.writeText(channel.forwarding_address!)
                                lemonToast.success('Forwarding address copied')
                            }}
                        />
                    </div>
                </div>
            ) : (
                <p className="mb-0 text-sm text-secondary">
                    A forwarding address is not available. Ask your PostHog administrator to configure the inbound email
                    domain.
                </p>
            )}
        </LemonCard>
    )
}

export function CustomerEmailConfig(): JSX.Element {
    const { channels, channelsLoadFailed, channelsLoading, connecting, emailDraft } =
        useValues(customerEmailConfigLogic)
    const { connectEmail, loadChannels, setEmailDraft } = useActions(customerEmailConfigLogic)

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
        <div className="flex max-w-2xl flex-col gap-4">
            {channels.map((channel) => (
                <ConnectedEmail key={channel.id} channel={channel} />
            ))}
            <div className="flex flex-col gap-2">
                <LemonLabel>{channels.length ? 'Connect another email' : 'Work email'}</LemonLabel>
                <p className="mb-0 text-sm text-secondary">
                    Connect the email address you use to talk to customers. PostHog matches forwarded conversations to
                    their accounts.
                </p>
                <div className="flex flex-wrap items-center gap-2">
                    <LemonInput
                        type="email"
                        value={emailDraft}
                        onChange={setEmailDraft}
                        placeholder="you@company.com"
                        className="min-w-72 flex-1"
                        disabled={connecting}
                        onPressEnter={connectEmail}
                    />
                    <LemonButton
                        type="primary"
                        loading={connecting}
                        disabledReason={emailDraft.trim() ? undefined : 'Enter your email address'}
                        onClick={connectEmail}
                    >
                        Connect email
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
