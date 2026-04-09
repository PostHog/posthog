import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconCheckCircle } from '@posthog/icons'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { SSO_PROVIDER_NAMES } from 'lib/constants'
import { SceneExport } from 'scenes/sceneTypes'

import type { SSOProvider } from '~/types'

const POSTHOG_CODE_CALLBACK_URL = 'posthog-code://callback'

function providerLabel(provider: string | undefined): string {
    if (!provider) {
        return 'Account'
    }
    return SSO_PROVIDER_NAMES[provider as SSOProvider] ?? provider
}

export const scene: SceneExport = {
    component: AccountSocialConnected,
}

/**
 * After OAuth links a social provider from PostHog Code (`next` → /account/social-connected?provider=…).
 * Redirects to `posthog-code://callback` with a fallback link if the app does not open.
 */
export function AccountSocialConnected(): JSX.Element {
    const { searchParams } = useValues(router)
    const provider = typeof searchParams.provider === 'string' ? searchParams.provider : undefined
    const label = providerLabel(provider)

    useEffect(() => {
        window.location.href = POSTHOG_CODE_CALLBACK_URL
    }, [])

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
