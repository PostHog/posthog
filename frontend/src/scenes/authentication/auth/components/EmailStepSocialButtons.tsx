import { useValues } from 'kea'

import { SocialLoginButtons } from 'lib/components/SocialLoginButton/SocialLoginButton'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { useLastLoginMethod } from 'scenes/authentication/shared/lastLoginMethod'

import { authLogic } from '../authLogic'
import { PrecheckResponseType, loginLogic } from '../loginLogic'

// A new person here signs in through the IdP. SAML normally replaces this row, but an account
// without a password still needs to see whatever methods it does have.
function hidesLoginRow(
    precheck: PrecheckResponseType,
    accountExists: boolean | null,
    isPasswordLoginUnavailable: boolean
): boolean {
    return (
        accountExists === false ||
        !!precheck.sso_enforcement ||
        (precheck.saml_available && !isPasswordLoginUnavailable)
    )
}

export function EmailStepSocialButtons(): JSX.Element | null {
    const { entry, step, accountExists } = useValues(authLogic)
    const { precheckResponse, isPasswordLoginUnavailable, restrictToProviders } = useValues(loginLogic)
    const { preflight } = useValues(preflightLogic)
    const lastLoginMethod = useLastLoginMethod()

    if (step === 'signup_credentials') {
        return preflight?.demo ? null : (
            <SocialLoginButtons topDivider caption="or sign up with" captionLocation="top" />
        )
    }
    if (step === 'login') {
        if (hidesLoginRow(precheckResponse, accountExists, isPasswordLoginUnavailable)) {
            return null
        }
        return (
            <SocialLoginButtons
                topDivider
                caption={isPasswordLoginUnavailable ? 'Log in with' : 'or log in with'}
                captionLocation="top"
                lastUsedProvider={lastLoginMethod}
                restrictToProviders={restrictToProviders}
                // Once we know the account's methods, only offer a passkey if it actually has
                // one — otherwise this is the same dead button we're removing.
                showPasskey={!isPasswordLoginUnavailable || !!precheckResponse.webauthn_credentials?.length}
            />
        )
    }
    if (preflight?.demo) {
        return null
    }
    return (
        <SocialLoginButtons
            topDivider
            caption="or continue with"
            captionLocation="top"
            lastUsedProvider={lastLoginMethod}
            showPasskey={entry === 'login'}
        />
    )
}
