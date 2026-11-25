import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { preflightLogic } from 'lib/logic/preflightLogic'

export function IPAllowListInfo(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!preflight?.public_egress_ip_addresses?.length) {
        return todayRailNav ? (
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Not supported
            </Text>
        ) : (
            <div>Not supported</div>
        )
    }

    const ipAddressesSnippet = (
        <CodeSnippet thing="IP addresses allowlisting">{preflight.public_egress_ip_addresses.join(' \n')}</CodeSnippet>
    )

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <Text size="xs" render={<p className="m-0" />}>
                    Whenever PostHog makes a call to an external service it will come from one of our static IP
                    addresses. If you need to explicitly allowlist these IPs, you can do so by adding them to your
                    firewall rules. This applies to all integrations such as webhooks, apps or batch exports.
                </Text>
                {ipAddressesSnippet}
            </div>
        )
    }

    return (
        <>
            <p>
                Whenever PostHog makes a call to an external service it will come from one of our static IP addresses.
                If you need to explicitly allowlist these IPs, you can do so by adding them to your firewall rules. This
                applies to all integrations such as webhooks, apps or batch exports.
            </p>

            {ipAddressesSnippet}
        </>
    )
}
