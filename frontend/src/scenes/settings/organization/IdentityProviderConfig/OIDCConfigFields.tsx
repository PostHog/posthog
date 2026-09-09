import { LemonBanner } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

export function OIDCConfigFields({
    siteUrl,
    hasClientSecret,
}: {
    siteUrl: string
    hasClientSecret: boolean
}): JSX.Element {
    return (
        <div className="space-y-4">
            <p>
                Create an OpenID Connect application in your identity provider. Use the authorization code flow with
                PKCE (S256). Add this redirect URL to the application.
            </p>
            <LemonField label="Redirect URL" name="_oidc_redirect_url">
                <CopyToClipboardInline>{`${siteUrl}/complete/oidc/`}</CopyToClipboardInline>
            </LemonField>
            <LemonField label="Issuer URL" name="oidc_issuer_url">
                <LemonInput placeholder="https://idp.example.com" autoComplete="off" />
            </LemonField>
            <LemonField label="Client ID" name="oidc_client_id">
                <LemonInput autoComplete="off" />
            </LemonField>
            <LemonField
                label="Client secret"
                name="oidc_client_secret"
                info={hasClientSecret ? 'A client secret is saved. Leave this empty to keep it.' : undefined}
            >
                <LemonInput
                    type="password"
                    autoComplete="new-password"
                    className="ph-no-capture"
                    data-attr="oidc-client-secret"
                />
            </LemonField>
            <LemonBanner type="info">
                Request the openid, profile, and email scopes. Your provider must include a verified email address in
                the ID token. The email must match a verified domain in this configuration.
            </LemonBanner>
        </div>
    )
}
