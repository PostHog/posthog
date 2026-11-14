import { useValues } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { type AuthStep, pendingOAuthConnectionProperties } from './authStepViewed'
import { type InboxProvider, inboxProviderLink } from './inboxProvider'

// pinned: autocapture selectors
const DATA_ATTR: Record<OpenInboxButtonProps['step'], string> = {
    verify_email: 'verify-email-open-inbox',
    login_code: 'login-code-open-inbox',
}

export interface OpenInboxButtonProps {
    provider: InboxProvider | null
    email: string | null
    step: Extract<AuthStep, 'verify_email' | 'login_code'>
    className?: string
}

export function OpenInboxButton({ provider, email, step, className }: OpenInboxButtonProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    // Reading the flag records an exposure, so only people with a recognized inbox read it.
    if (!provider || featureFlags[FEATURE_FLAGS.OPEN_INBOX_BUTTON] !== 'test') {
        return null
    }

    const { name, url } = inboxProviderLink(provider, email)
    return (
        <LemonButton
            type="secondary"
            size="large"
            center
            fullWidth
            className={className}
            to={url}
            targetBlank
            onClick={() =>
                // pinned: analytics event and property names
                posthog.capture('open inbox clicked', {
                    inbox_provider: provider,
                    step,
                    ...pendingOAuthConnectionProperties(),
                })
            }
            data-attr={DATA_ATTR[step]}
        >
            {`Open ${name}`}
        </LemonButton>
    )
}
