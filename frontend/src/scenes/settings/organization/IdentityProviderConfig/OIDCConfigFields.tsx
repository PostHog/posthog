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
                <p>
                    In your identity provider, allow this OIDC application to request the <code>openid</code>,{' '}
                    <code>profile</code>, and <code>email</code> scopes. PostHog requests these scopes when a user signs
                    in.
                </p>
                <p>The ID token must include these claims:</p>
                <ul className="list-disc pl-4">
                    <li>
                        <code>sub</code>: a stable identifier for the user
                    </li>
                    <li>
                        <code>email</code>: the user's email address
                    </li>
                    <li>
                        <code>email_verified</code>: <code>true</code>
                    </li>
                </ul>
                <p>
                    The email address in the <code>email</code> claim must use a domain verified in this configuration.
                </p>
            </LemonBanner>
        </div>
    )
}
