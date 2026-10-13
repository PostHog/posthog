import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonLabel } from '@posthog/lemon-ui'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

export function EmailForwardingAddress({ forwardingAddress }: { forwardingAddress: string }): JSX.Element {
    return (
        <div>
            <LemonLabel>Forwarding address</LemonLabel>
            <p className="text-xs text-muted-alt mb-1">
                Forward incoming emails to this address in your email provider.
            </p>
            <div className="flex items-center gap-2">
                <code className="bg-surface-primary px-2 py-1 rounded text-sm break-all">{forwardingAddress}</code>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconCopy />}
                    tooltip="Copy forwarding address"
                    onClick={() => {
                        void navigator.clipboard.writeText(forwardingAddress)
                        lemonToast.success('Forwarding address copied')
                    }}
                />
            </div>
            <div className="text-xs text-muted-alt mt-2 flex flex-col gap-0.5">
                <p className="mb-0">
                    <strong>Gmail:</strong> Settings → Forwarding → Add a forwarding address
                </p>
                <p className="mb-0">
                    <strong>Outlook:</strong> Settings → Mail → Forwarding → Enable forwarding
                </p>
            </div>
        </div>
    )
}
