import { useValues } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { type AuthStep, pendingOAuthConnectionProperties } from './authStepViewed'
import { type InboxProvider, inboxProviderLink } from './inboxProvider'

// pinned: autocapture selectors
const DATA_ATTR: Record<OpenInboxLinkProps['step'], string> = {
    verify_email: 'verify-email-open-inbox',
    login_code: 'login-code-open-inbox',
}

export interface OpenInboxLinkProps {
    provider: InboxProvider | null
    email: string | null
    step: Extract<AuthStep, 'verify_email' | 'login_code'>
}

export function OpenInboxLink({ provider, email, step }: OpenInboxLinkProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    // Reading the flag records an exposure, so only people with a recognized inbox read it.
    if (!provider || featureFlags[FEATURE_FLAGS.OPEN_INBOX_BUTTON] !== 'test') {
        return null
    }

    const { name, url } = inboxProviderLink(provider, email)
    return (
        <Link
            to={url}
            target="_blank"
            className="font-semibold whitespace-nowrap no-underline hover:underline hover:underline-offset-2 text-warning"
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
            {`Check your ${name} inbox`}
        </Link>
    )
}
