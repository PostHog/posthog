import { useValues } from 'kea'

import { SSOEnforcedLoginButton } from 'lib/components/SocialLoginButton/SocialLoginButton'
import { useLastLoginMethod } from 'scenes/authentication/shared/lastLoginMethod'

import { loginLogic } from '../loginLogic'

export function LoginSingleSignOnButtons(): JSX.Element {
    const { precheckResponse, login } = useValues(loginLogic)
    const lastLoginMethod = useLastLoginMethod()

    return (
        <>
            {precheckResponse.sso_enforcement && (
                <SSOEnforcedLoginButton
                    provider={precheckResponse.sso_enforcement}
                    email={login.email}
                    isLastUsed={lastLoginMethod === precheckResponse.sso_enforcement}
                />
            )}
            {precheckResponse.saml_available && !precheckResponse.sso_enforcement && (
                <SSOEnforcedLoginButton provider="saml" email={login.email} isLastUsed={lastLoginMethod === 'saml'} />
            )}
            {precheckResponse.oidc_available && !precheckResponse.sso_enforcement && (
                <SSOEnforcedLoginButton provider="oidc" email={login.email} isLastUsed={lastLoginMethod === 'oidc'} />
            )}
        </>
    )
}
