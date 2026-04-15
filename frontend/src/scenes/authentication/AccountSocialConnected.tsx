import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconCheckCircle } from '@posthog/icons'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { SSO_PROVIDER_NAMES } from 'lib/constants'
import { SceneExport } from 'scenes/sceneTypes'

import type { SSOProvider } from '~/types'

const POSTHOG_CODE_CALLBACK_URL = 'posthog-code://callback'

const INTEGRATION_LABELS: Record<string, string> = {
    github: 'GitHub',
    linear: 'Linear',
}

function providerLabel(provider: string | undefined): string {
    if (!provider) {
        return 'Account'
    }
    return SSO_PROVIDER_NAMES[provider as SSOProvider] ?? provider
}

function integrationLabel(integration: string | undefined): string {
    if (!integration) {
        return 'Integration'
    }
    return INTEGRATION_LABELS[integration] ?? integration
}

export const scene: SceneExport = {
    component: AccountSocialConnected,
}

/**
 * Landing page shown after completing an OAuth flow initiated from PostHog Code.
 *
 * Two modes:
 * - SSO provider linked: `?provider=…` → redirects back to the app via deep link
 * - Integration connected: `?integration=…` → tells the user to return to the app
 */
export function AccountSocialConnected(): JSX.Element {
    const { searchParams } = useValues(router)
    const provider = typeof searchParams.provider === 'string' ? searchParams.provider : undefined
    const integration = typeof searchParams.integration === 'string' ? searchParams.integration : undefined

    useEffect(() => {
        if (provider) {
            window.location.href = POSTHOG_CODE_CALLBACK_URL
        }
    }, [provider])

    if (integration) {
        const label = integrationLabel(integration)
        return (
            <BridgePage view="account-connected">
                <div className="flex flex-col items-center gap-4 text-center max-w-lg mx-auto">
                    <IconCheckCircle className="text-success text-5xl shrink-0" />
                    <h2 className="text-xl font-semibold m-0">{label} connected</h2>
                    <p className="text-muted mb-0">You can now close this page and return to PostHog Code.</p>
                </div>
            </BridgePage>
        )
    }

    const label = providerLabel(provider)
    return (
        <BridgePage view="account-social-connected">
            <div className="flex flex-col items-center gap-4 text-center max-w-lg mx-auto">
                <IconCheckCircle className="text-success text-5xl shrink-0" />
                <h2 className="text-xl font-semibold m-0">{label} linked to account</h2>
                <p className="text-muted mb-0">You can now log into PostHog using {label}.</p>
                <p className="text-muted mb-0">
                    <strong>Returning to PostHog Code…</strong>
                    <br />
                    <em>If this hasn't happened automatically, get back to the PostHog Code app manually.</em>
                </p>
            </div>
        </BridgePage>
    )
}
