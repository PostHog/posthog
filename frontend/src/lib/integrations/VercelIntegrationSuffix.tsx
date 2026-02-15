import { LemonButton } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'

import { IntegrationType } from '~/types'

export function VercelIntegrationSuffix({ integration }: { integration: IntegrationType }): JSX.Element {
    const accountUrl = integration.config?.account?.url
    const accountName = integration.config?.account?.name

    if (!accountUrl) {
        return <></>
    }

    return (
        <LemonButton
            type="secondary"
            to={accountUrl}
            targetBlank
            sideIcon={<IconOpenInNew />}
            tooltip={accountName ? `Open ${accountName} in Vercel` : 'Open in Vercel'}
        >
            View in Vercel
        </LemonButton>
    )
}
