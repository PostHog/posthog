import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'

export function XAAManagedConfig({
    applicationName,
    issuerUrl,
    verifiedDomains,
}: {
    applicationName: string
    issuerUrl: string
    verifiedDomains: string[]
}): JSX.Element {
    return (
        <div className="space-y-4">
            <LemonBanner type="warning">
                {applicationName} manages this configuration through enterprise-managed auth. PostHog trusts{' '}
                {applicationName} to sign in any member of this organization whose email is on a verified domain,
                without that member approving the connection. You can't edit it here. To change it, set it up again from{' '}
                {applicationName}. To stop trusting {applicationName}, delete this configuration.
            </LemonBanner>
            <div className="space-y-1">
                <LemonLabel>Managed by</LemonLabel>
                <p className="m-0">{applicationName}</p>
            </div>
            <div className="space-y-1">
                <LemonLabel>Identity provider issuer URL</LemonLabel>
                <p className="m-0 font-mono break-all">{issuerUrl}</p>
            </div>
            <div className="space-y-1">
                <LemonLabel>Domains</LemonLabel>
                <p className="m-0">
                    {verifiedDomains.length
                        ? `All verified domains: ${verifiedDomains.join(', ')}`
                        : 'All verified domains. This organization has none, so no one can sign in through it yet.'}
                </p>
            </div>
        </div>
    )
}
