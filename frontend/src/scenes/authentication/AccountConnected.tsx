import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconCheckCircle } from '@posthog/icons'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { SSO_PROVIDER_NAMES } from 'lib/constants'
import { SceneExport } from 'scenes/sceneTypes'

import type { SSOProvider } from '~/types'

const POSTHOG_CODE_DEEP_LINK = 'posthog-code://integration'

function posthogCodeDeepUrl(searchParams: Record<string, unknown>): string {
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

/** Path segment under {@link urls.accountConnected} — SSO link vs GitHub user integration. */
export type AccountConnectedKind = 'github-login' | 'github-integration' | 'invalid'

export interface AccountConnectedProps {
    kind: AccountConnectedKind
}

function providerLabel(provider: string | undefined): string {
    if (!provider) {
        return 'Account'
    }
    return SSO_PROVIDER_NAMES[provider as SSOProvider] ?? provider
}

function headline(kind: 'github-login' | 'github-integration', label: string, isError: boolean): string {
    if (kind === 'github-integration') {
        return isError ? `${label} connection failed` : `${label} connected`
    }
    return isError ? `${label} linking failed` : `${label} linked to account`
}

export const scene: SceneExport<AccountConnectedProps> = {
    component: AccountConnected,
    paramsToProps: ({ params: { kind: raw } }) => {
        const kind: AccountConnectedKind = raw === 'github-login' || raw === 'github-integration' ? raw : 'invalid'
        return { kind }
    },
}

/**
 * Unified return page for PostHog Code / web: social SSO link (`github-login`) or
 * personal GitHub integration (`github-integration`). Navigates to `posthog-code://integration?…` for the desktop app.
 */
export function AccountConnected({ kind }: AccountConnectedProps): JSX.Element {
    const { searchParams } = useValues(router)
    const provider = typeof searchParams.provider === 'string' ? searchParams.provider : undefined
    const label = providerLabel(provider)
    const isError = typeof searchParams.error === 'string' && searchParams.error.length > 0

    useEffect(() => {
        if (kind !== 'invalid') {
            window.location.href = posthogCodeDeepUrl(searchParams)
        }
    }, [kind, searchParams])

    if (kind === 'invalid') {
        return (
            <BridgePage view="account-connected">
                <div className="flex flex-col items-center gap-4 text-center max-w-lg mx-auto">
                    <p className="text-muted mb-0">
                        This link is not valid. Return to PostHog from the product you started from.
                    </p>
                </div>
            </BridgePage>
        )
    }

    const showLoginLine = kind === 'github-login' && !isError

    return (
        <BridgePage view="account-connected">
            <div className="flex flex-col items-center gap-4 text-center max-w-lg mx-auto">
                <IconCheckCircle className="text-success text-5xl shrink-0" />
                <h2 className="text-xl font-semibold m-0">{headline(kind, label, isError)}</h2>
                {showLoginLine && <p className="text-muted mb-0">You can now log into PostHog using {label}.</p>}
                <p className="text-muted mb-0">
                    <strong>Returning to PostHog Code…</strong>
                    <br />
                    <em>If this hasn't happened automatically, get back to the PostHog Code app manually.</em>
                </p>
            </div>
        </BridgePage>
    )
}
