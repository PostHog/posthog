import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { SSO_PROVIDER_NAMES } from 'lib/constants'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

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
 * After OAuth links a social provider to the existing account (`next` → /account/social-connected?provider=&connect_from=).
 * `connect_from=posthog_code`: redirect to `posthog-code://callback` and fallback link (set `connect_from` on `/login/<backend>/` from PostHog Code).
 */
export function AccountSocialConnected(): JSX.Element {
    const { searchParams } = useValues(router)
    const provider = typeof searchParams.provider === 'string' ? searchParams.provider : undefined
    const connectFrom = typeof searchParams.connect_from === 'string' ? searchParams.connect_from : undefined
    const label = providerLabel(provider)
    const fromPostHogCode = connectFrom === 'posthog_code'

    useEffect(() => {
        if (!fromPostHogCode) {
            return
        }
        window.location.href = POSTHOG_CODE_CALLBACK_URL
    }, [fromPostHogCode])

    return (
        <BridgePage view="account-social-connected">
            <div className="flex flex-col items-center gap-4 text-center max-w-md mx-auto">
                <IconCheckCircle className="text-success text-5xl shrink-0" />
                <h2 className="text-xl font-semibold m-0">{label} connected</h2>
                {fromPostHogCode ? (
                    <p className="text-muted mb-0">
                        Opening <strong>PostHog Code</strong>… If nothing happens, use the link below. You can also
                        close this tab.
                    </p>
                ) : (
                    <p className="text-muted mb-0">
                        This sign-in method is now linked to your PostHog account. You can close this tab or continue
                        below.
                    </p>
                )}
                {fromPostHogCode ? (
                    <Link to={POSTHOG_CODE_CALLBACK_URL} className="font-medium text-primary underline">
                        Continue in PostHog Code
                    </Link>
                ) : (
                    <LemonButton type="primary" size="large" to={urls.default()}>
                        Continue in PostHog
                    </LemonButton>
                )}
            </div>
        </BridgePage>
    )
}
