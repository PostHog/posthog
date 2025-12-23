import { LemonButton } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'

import { IntegrationType } from '~/types'

export function VercelIntegrationSuffix({
    integration,
    onDelete,
    disabledReason,
}: {
    integration: IntegrationType
    onDelete: () => void
    disabledReason?: string
}): JSX.Element {
    const accountUrl = integration.config?.account?.url
    const accountName = integration.config?.account?.name

    return (
        <div className="flex gap-2">
            {accountUrl && (
                <LemonButton
                    type="secondary"
                    to={accountUrl}
                    targetBlank
                    sideIcon={<IconOpenInNew />}
                    tooltip={accountName ? `Open ${accountName} in Vercel` : 'Open in Vercel'}
                >
                    View in Vercel
                </LemonButton>
            )}
            <LemonButton
                type="secondary"
                status="danger"
                onClick={onDelete}
                disabledReason={disabledReason}
                tooltip={disabledReason}
            >
                Disconnect
            </LemonButton>
        </div>
    )
}
