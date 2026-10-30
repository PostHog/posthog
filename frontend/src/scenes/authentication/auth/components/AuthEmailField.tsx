import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { usePrevious } from 'lib/hooks/usePrevious'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { isWebKitBrowser } from 'lib/utils/dom'
import { isEmail } from 'lib/utils/url'

import { authLogic } from '../authLogic'
import { loginLogic } from '../loginLogic'

export function AuthEmailField(): JSX.Element {
    const { login, precheckResponse } = useValues(loginLogic)
    const { setLoginValue, precheck } = useActions(loginLogic)
    const { entry, emailError } = useValues(authLogic)
    const prevEmail = usePrevious(login.email)

    // An autofilled address is prechecked at once, so a passkey prompt can open before Continue
    useEffect(() => {
        const charDelta = login.email.length - (prevEmail?.length ?? 0)
        const isAutofill = charDelta > 1

        if (isAutofill && isEmail(login.email, { requireTLD: true }) && precheckResponse.status === 'pending') {
            precheck({ email: login.email })
        }
    }, [login.email, prevEmail, precheckResponse.status, precheck])

    return (
        <LemonField.Pure label="Email" htmlFor="auth-email" error={emailError}>
            <LemonInput
                id="auth-email"
                className="ph-ignore-input"
                // pinned: Playwright and autocapture select these per entry URL
                data-attr={entry === 'signup' ? 'signup-email' : 'login-email'}
                type="email"
                autoFocus
                placeholder="you@yourcompany.com"
                // The `webauthn` token enables passkey autofill (conditional UI),
                // which we only offer on WebKit; elsewhere the auto-modal handles passkeys.
                autoComplete={isWebKitBrowser() ? 'username webauthn' : 'username'}
                value={login.email}
                onChange={(value) => setLoginValue('email', value)}
                status={emailError ? 'danger' : 'default'}
                fullWidth
            />
        </LemonField.Pure>
    )
}
