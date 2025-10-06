import { useValues } from 'kea'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

export function IPAllowListInfo(): JSX.Element {
    const { preflight } = useValues(preflightLogic)

    if (!preflight?.public_egress_ip_addresses?.length) {
        return <div>Not supported</div>
    }
    return (
        <>
            <p>
                Whenever PostHog makes a call to an external service it will come from one of our static IP addresses.
                If you need to explicitly allowlist these IPs, you can do so by adding them to your firewall rules. This
                applies to all integrations such as webhooks, apps or batch exports.
            </p>

            <CodeSnippet thing="IP addresses allowlisting">
                {preflight.public_egress_ip_addresses.join(' \n')}
            </CodeSnippet>
        </>
    )
}
