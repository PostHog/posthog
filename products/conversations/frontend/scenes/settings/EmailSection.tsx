import { useActions, useValues } from 'kea'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonCard, LemonDivider, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { supportSettingsLogic } from './supportSettingsLogic'

export function EmailSection(): JSX.Element {
    return (
        <SceneSection
            title="Email channel"
            description="Receive customer emails as support tickets. Set up forwarding from your email provider to route emails into conversations."
            className="mt-4"
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-2 max-w-[800px] px-4 py-3">
                <EmailChannelSection />
            </LemonCard>
        </SceneSection>
    )
}

function EmailChannelSection(): JSX.Element {
    const { emailConnected, emailFromEmail, emailFromName, emailConnecting, emailForwardingAddress } =
        useValues(supportSettingsLogic)
    const { setEmailFromEmail, setEmailFromName, connectEmail, disconnectEmail } = useActions(supportSettingsLogic)

    return (
        <div className="flex flex-col gap-y-2">
            {!emailConnected ? (
                <>
                    <div>
                        <label className="font-medium">Connect email</label>
                        <p className="text-xs text-muted-alt">
                            Enter the email address customers will contact you at (e.g. support@company.com). We'll give
                            you a forwarding address to set up in your email provider.
                        </p>
                    </div>
                    <div className="flex flex-col gap-2">
                        <LemonInput
                            value={emailFromEmail}
                            onChange={(value) => setEmailFromEmail(value)}
                            placeholder="support@company.com"
                            fullWidth
                        />
                        <LemonInput
                            value={emailFromName}
                            onChange={(value) => setEmailFromName(value)}
                            placeholder="Display name (e.g. Acme Support)"
                            fullWidth
                        />
                        <div>
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={connectEmail}
                                loading={emailConnecting}
                                disabledReason={
                                    !emailFromEmail || !emailFromName
                                        ? 'Enter email address and display name'
                                        : undefined
                                }
                            >
                                Connect email
                            </LemonButton>
                        </div>
                    </div>
                </>
            ) : (
                <>
                    <div>
                        <label className="font-medium">Connection</label>
                        <LemonTag type="success" className="ml-2">
                            Connected
                        </LemonTag>
                    </div>
                    {emailForwardingAddress && (
                        <>
                            <LemonDivider />
                            <div>
                                <label className="font-medium">Forwarding address</label>
                                <p className="text-xs text-muted-alt">
                                    Set up a forwarding rule in your email provider to forward incoming emails to this
                                    address.
                                </p>
                                <div className="flex items-center gap-2 mt-1">
                                    <code className="bg-surface-primary px-2 py-1 rounded text-sm break-all">
                                        {emailForwardingAddress}
                                    </code>
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        icon={<IconCopy />}
                                        onClick={() => {
                                            void navigator.clipboard.writeText(emailForwardingAddress)
                                            lemonToast.success('Copied to clipboard')
                                        }}
                                    />
                                </div>
                            </div>
                            <LemonDivider />
                            <div>
                                <label className="font-medium">Setup instructions</label>
                                <div className="text-xs text-muted-alt mt-1 flex flex-col gap-1">
                                    <p className="mb-0">
                                        <strong>Gmail:</strong> Settings → Forwarding → Add a forwarding address → paste
                                        the address above → confirm.
                                    </p>
                                    <p className="mb-0">
                                        <strong>Outlook:</strong> Settings → Mail → Forwarding → Enable forwarding →
                                        paste the address above.
                                    </p>
                                    <p className="mb-0">
                                        <strong>Other:</strong> Set up a forwarding rule to send all incoming emails to
                                        the address above.
                                    </p>
                                </div>
                            </div>
                        </>
                    )}
                    <LemonDivider />
                    <div className="flex justify-end">
                        <LemonButton
                            type="secondary"
                            status="danger"
                            size="small"
                            onClick={() => {
                                LemonDialog.open({
                                    title: 'Disconnect email?',
                                    description:
                                        'This will stop creating tickets from emails. Existing tickets will not be affected.',
                                    primaryButton: {
                                        status: 'danger',
                                        children: 'Disconnect',
                                        onClick: disconnectEmail,
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }}
                        >
                            Disconnect email
                        </LemonButton>
                    </div>
                </>
            )}
        </div>
    )
}
