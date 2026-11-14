import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { AuthStep } from './authStepViewed'
import { type InboxProvider, captureOpenInboxClicked, inboxProviderLink } from './inboxProvider'

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

    // Read the flag only when there is a button to show, so the experiment exposes only the
    // people whose inbox the backend recognized. Reading it records an exposure.
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
            onClick={() => captureOpenInboxClicked(provider, step)}
            data-attr={DATA_ATTR[step]}
        >
            {`Open ${name}`}
        </LemonButton>
    )
}
