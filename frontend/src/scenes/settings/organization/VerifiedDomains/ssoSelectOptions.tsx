import { SocialLoginIcon } from 'lib/components/SocialLoginButton/SocialLoginIcon'
import { SSO_PROVIDER_NAMES } from 'lib/constants'
import { LemonSelectOptionLeaf } from 'lib/lemon-ui/LemonSelect/LemonSelect'

import { PreflightStatus, SSOProvider } from '~/types'

export function ssoSelectOptions(
    preflight: PreflightStatus,
    samlAvailable: boolean,
    oidcAvailable: boolean | undefined
): LemonSelectOptionLeaf<SSOProvider | ''>[] {
    const authProviders = Object.keys(preflight.available_social_auth_providers) as SSOProvider[]
    const options: LemonSelectOptionLeaf<SSOProvider | ''>[] = [{ value: '', label: "Don't enforce" }]

    authProviders.forEach((key) => {
        options.push({
            value: key,
            label: SSO_PROVIDER_NAMES[key],
            disabledReason: preflight.available_social_auth_providers[key]
                ? undefined
                : 'This provider is not configured.',
            icon: <SocialLoginIcon provider={key} className="w-4 h-4" />,
        })
    })

    options.push({
        value: 'saml',
        label: SSO_PROVIDER_NAMES['saml'],
        disabledReason: !samlAvailable ? 'This provider is not configured.' : undefined,
        icon: <SocialLoginIcon provider="saml" className="w-4 h-4" />,
    })

    if (oidcAvailable !== undefined) {
        options.push({
            value: 'oidc',
            label: SSO_PROVIDER_NAMES.oidc,
            disabledReason: oidcAvailable ? undefined : 'This provider is not configured.',
            icon: <SocialLoginIcon provider="oidc" className="w-4 h-4" />,
        })
    }

    return options
}
