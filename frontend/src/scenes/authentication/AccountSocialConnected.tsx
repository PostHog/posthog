import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconCheckCircle } from '@posthog/icons'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { SSO_PROVIDER_NAMES } from 'lib/constants'
import { SceneExport } from 'scenes/sceneTypes'

import type { SSOProvider } from '~/types'

const POSTHOG_CODE_DEEP_LINK = 'posthog-code://integration'

function providerLabel(provider: string | undefined): string {
    if (!provider) {
        return 'Account'
    }
    return SSO_PROVIDER_NAMES[provider as SSOProvider] ?? provider
}

function buildDeepLinkUrl(searchParams: Record<string, unknown>): string {
    const url = new URL(POSTHOG_CODE_DEEP_LINK)

    const provider = typeof searchParams.provider === 'string' ? searchParams.provider : ''
    if (provider) {
        url.searchParams.set('provider', provider)
    }

    for (const key of ['project_id', 'installation_id'] as const) {
        const value = searchParams[key]
        if (value !== undefined && value !== null && value !== '') {
            url.searchParams.set(key, String(value))
        }
    }

    const errorCode = typeof searchParams.error === 'string' ? searchParams.error : ''
    url.searchParams.set('status', errorCode ? 'error' : 'success')
    if (errorCode) {
        url.searchParams.set('error_code', errorCode)
        const errorMessage = typeof searchParams.error_message === 'string' ? searchParams.error_message : ''
        if (errorMessage) {
            url.searchParams.set('error_message', errorMessage)
        }
    }

    return url.toString()
}

export const scene: SceneExport = {
    component: AccountSocialConnected,
}

/**
 * Landing page after a PostHog Code flow completes on the web — social login linking
 * (`next=/account/social-connected?provider=…&connect_from=posthog_code`) or GitHub App
 * install (Twig sets `next` to this page via `connect_from=posthog_code`).
 *
 * Deep-links back to the Twig app via `posthog-code://integration?...`, forwarding the
 * provider / project_id / installation_id and a status flag so Twig can close its
 * pending flow without polling. Falls back to copy + manual switch-back if the protocol
 * handler is not registered.
 */
export function AccountSocialConnected(): JSX.Element {
    const { searchParams } = useValues(router)
    const provider = typeof searchParams.provider === 'string' ? searchParams.provider : undefined
    const label = providerLabel(provider)
    const isError = typeof searchParams.error === 'string' && searchParams.error.length > 0

    useEffect(() => {
        window.location.href = buildDeepLinkUrl(searchParams)
    }, [searchParams])

    return (
        <BridgePage view="account-social-connected">
            <div className="flex flex-col items-center gap-4 text-center max-w-lg mx-auto">
                <IconCheckCircle className="text-success text-5xl shrink-0" />
                <h2 className="text-xl font-semibold m-0">
                    {isError ? `${label} linking failed` : `${label} linked to account`}
                </h2>
                {!isError && <p className="text-muted mb-0">You can now log into PostHog using {label}.</p>}
                <p className="text-muted mb-0">
                    <strong>Returning to PostHog Code…</strong>
                    <br />
                    <em>If this hasn't happened automatically, get back to the PostHog Code app manually.</em>
                </p>
            </div>
        </BridgePage>
    )
}
