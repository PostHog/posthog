import { useValues } from 'kea'

import { Card, CardContent, CardHeader, CardTitle, Text } from '@posthog/quill'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { DomainConnectBanner } from 'lib/components/DomainConnect'

import { proxyLogic } from './proxyLogic'

export function QuillProxyWaitingRecords(): JSX.Element | null {
    const { proxyRecords } = useValues(proxyLogic)

    const waitingRecords = proxyRecords.filter((r) => r.status === 'waiting')

    if (waitingRecords.length === 0) {
        return null
    }

    return (
        <Card size="sm">
            <CardHeader>
                <CardTitle>Almost there</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
                <Text size="xs" render={<p className="m-0" />}>
                    You need to set the following <b>CNAME</b> records in your DNS provider:
                </Text>
                {waitingRecords.map((r) => (
                    <div key={r.id} className="flex flex-col gap-1">
                        <Text size="xs" weight="semibold" render={<span />}>
                            {r.domain}
                        </Text>
                        <CodeSnippet language={Language.HTTP}>{r.target_cname}</CodeSnippet>
                        <DomainConnectBanner
                            logicKey={`proxy-${r.id}`}
                            domain={r.domain}
                            context="proxy"
                            proxyRecordId={r.id}
                        />
                    </div>
                ))}
                <Text size="xs" render={<p className="m-0" />}>
                    <strong>Important:</strong> If you are using a DNS provider like Cloudflare that offers proxy
                    options (orange cloud), make sure the proxy is <strong>disabled</strong> (gray cloud) for this
                    domain. Enabling the proxy at your DNS provider may interfere with the managed reverse proxy
                    functionality.
                </Text>
            </CardContent>
        </Card>
    )
}
