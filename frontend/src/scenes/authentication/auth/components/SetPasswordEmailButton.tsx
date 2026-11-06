import { useActions, useValues } from 'kea'

import { IconLetter } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { loginLogic } from '../loginLogic'

export function SetPasswordEmailButton(): JSX.Element {
    const { login, setPasswordLinkSentToLoading } = useValues(loginLogic)
    const { sendSetPasswordLink } = useActions(loginLogic)

    return (
        <LemonButton
            size="large"
            icon={<IconLetter className="w-7 h-7" />}
            tooltip="Email me a link to set a password"
            aria-label="Email me a link to set a password"
            htmlType="button"
            // Autocapture reports the click. Each reset entry point has its own `data-attr`, so one
            // funnel can tell them apart.
            data-attr="login-no-method-reset-password"
            loading={setPasswordLinkSentToLoading}
            onClick={() => sendSetPasswordLink(login.email)}
        />
    )
}
