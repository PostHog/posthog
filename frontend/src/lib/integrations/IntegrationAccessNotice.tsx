import { LemonBanner } from '@posthog/lemon-ui'

/** Keyed by integration kind. A kind without an entry gets no notice. */
const ACCESS_NOTICES: Record<string, JSX.Element> = {
    'google-ads': (
        <div className="flex flex-col gap-2">
            <p className="mb-0">
                Google asks for read and write access to your Google Ads account. Google publishes no read-only scope
                for Google Ads, so PostHog cannot request less.
            </p>
            <p className="mb-0">
                Importing your Google Ads data only reads from the account. PostHog writes to it only if you set up a
                conversions destination.
            </p>
            <p className="mb-0">
                To limit what PostHog can do, connect a Google account that has read-only access to the Google Ads
                account.
            </p>
        </div>
    ),
}

/**
 * Explains what an OAuth connection grants, for providers that publish no scope narrow enough
 * for what PostHog does with the connection. Rendered before the user reaches the consent
 * screen, and again on the connected integration.
 */
export function IntegrationAccessNotice({ kind }: { kind: string }): JSX.Element | null {
    const notice = ACCESS_NOTICES[kind]
    if (!notice) {
        return null
    }
    return (
        <LemonBanner type="info" className="text-sm">
            {notice}
        </LemonBanner>
    )
}
