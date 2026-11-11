import { Link } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

export function XAAConfigFields({
    isReady,
    registeredByApplicationName,
}: {
    isReady: boolean
    registeredByApplicationName: string | null
}): JSX.Element {
    return (
        <div className="space-y-4">
            {registeredByApplicationName && (
                <LemonBanner type="warning">
                    {registeredByApplicationName} set this up through enterprise-managed auth. PostHog trusts{' '}
                    {registeredByApplicationName} to sign in any member of this organization whose email is on the
                    domains below, without that member approving the connection. Changing the issuer URL breaks the{' '}
                    {registeredByApplicationName} connection. To stop trusting {registeredByApplicationName}, delete
                    this configuration.
                </LemonBanner>
            )}
            <p>
                Configure XAA for your organization.{' '}
                <Link to="https://posthog.com/docs/settings/id-jag" target="_blank" targetBlankIcon>
                    Read the XAA setup guide
                </Link>
            </p>
            <LemonField
                name="id_jag_issuer_url"
                label="Identity provider issuer URL"
                info="This must match the iss claim on ID-JAG tokens."
            >
                <LemonInput className="ph-ignore-input" placeholder="https://idp.example.com" autoComplete="off" />
            </LemonField>
            <LemonField
                name="id_jag_jwks_url"
                label="JWKS URL (optional)"
                info="Leave this empty to use OIDC discovery from the issuer URL."
            >
                <LemonInput
                    className="ph-ignore-input"
                    placeholder="https://idp.example.com/.well-known/jwks.json"
                    autoComplete="off"
                />
            </LemonField>
            <LemonField
                name="id_jag_allowed_clients"
                label="Allowed client IDs (optional)"
                info="Leave this empty to accept any client_id value."
            >
                <LemonInputSelect placeholder="Add client IDs" mode="multiple" allowCustomValues options={[]} />
            </LemonField>
            {!isReady && (
                <LemonBanner type="info">
                    XAA remains disabled until you enter an identity provider issuer URL. You can save a partial
                    configuration.
                </LemonBanner>
            )}
            <LemonBanner type="info">
                Grant <code>user:read</code> and the scopes required by each integration. Project APIs also require{' '}
                <code>organization:read</code> and <code>project:read</code>.
            </LemonBanner>
        </div>
    )
}
