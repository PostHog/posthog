import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

export function OIDCConfigFields({
    siteUrl,
    hasClientSecret,
    clientSecretCleared,
    onClearClientSecret,
}: {
    siteUrl: string
    hasClientSecret: boolean
    clientSecretCleared: boolean
    onClearClientSecret: () => void
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
            <LemonField label="Client secret" name="oidc_client_secret">
                {hasClientSecret && !clientSecretCleared ? (
                    <div className="space-y-3">
                        <p className="text-secondary mb-0">
                            A client secret is saved. You cannot view it after saving. Update it to enter a new client
                            secret.
                        </p>
                        <LemonButton
                            type="secondary"
                            onClick={onClearClientSecret}
                            data-attr="clear-oidc-client-secret"
                        >
                            Update client secret
                        </LemonButton>
                    </div>
                ) : (
                    <LemonInput
                        type="password"
                        autoComplete="new-password"
                        className="ph-no-capture"
                        data-attr="oidc-client-secret"
                    />
                )}
            </LemonField>
            <LemonBanner type="info">
                <p>
                    In your identity provider, allow this OIDC application to request the <code>openid</code>,{' '}
                    <code>profile</code>, and <code>email</code> scopes. PostHog requests these scopes when a user signs
                    in.
                </p>
                <p>
                    PostHog reads the user's identity from the <code>userinfo</code> endpoint of your identity provider.
                    The response must include these claims:
                </p>
                <ul className="list-disc pl-4">
                    <li>
                        <code>sub</code>: a stable identifier for the user. It must match the <code>sub</code> claim in
                        the ID token.
                    </li>
                    <li>
                        <code>email</code>: the user's email address
                    </li>
                    <li>
                        <code>email_verified</code>: must be <code>true</code>. Sign-in fails if your identity provider
                        omits this claim, or sends <code>false</code> or the string <code>"true"</code>.
                    </li>
                </ul>
                <p>The email address must use a domain verified in this configuration.</p>
            </LemonBanner>
        </div>
    )
}
