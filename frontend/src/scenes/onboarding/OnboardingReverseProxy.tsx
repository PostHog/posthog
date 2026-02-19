import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect } from 'react'

import { IconCheckCircle } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCollapse, LemonInput, Spinner, Tooltip } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { DomainConnectBanner } from 'lib/components/DomainConnect'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { ProxyRecord, proxyLogic } from 'scenes/settings/environment/proxyLogic'

import { OnboardingStepKey } from '~/types'

import { OnboardingStep } from './OnboardingStep'
import { OnboardingStepComponentType } from './onboardingLogic'

export const OnboardingReverseProxy: OnboardingStepComponentType = () => {
    const { proxyRecords, proxyRecordsLoading } = useValues(proxyLogic)
    const { acknowledgeCloudflareOptIn, showForm } = useActions(proxyLogic)

    useEffect(() => {
        showForm()
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    // Acknowledge Cloudflare opt-in when a record is successfully created
    const hasRecords = proxyRecords.length > 0
    useEffect(() => {
        if (hasRecords) {
            acknowledgeCloudflareOptIn()
        }
    }, [hasRecords]) // eslint-disable-line react-hooks/exhaustive-deps

    const hasValidRecord = proxyRecords.some((r) => r.status === 'valid')
    const waitingRecords = proxyRecords.filter((r) => r.status === 'waiting' || r.status === 'issuing')

    const content = hasValidRecord ? (
        <ProxyVerified record={proxyRecords.find((r) => r.status === 'valid')!} />
    ) : waitingRecords.length > 0 ? (
        <WaitingForDns records={waitingRecords} />
    ) : (
        <AddDomainForm proxyRecordsLoading={proxyRecordsLoading} />
    )

    return (
        <OnboardingStep title="Set up a reverse proxy (optional)" stepKey={OnboardingStepKey.REVERSE_PROXY} showSkip>
            {content}
        </OnboardingStep>
    )
}

OnboardingReverseProxy.stepKey = OnboardingStepKey.REVERSE_PROXY

function AddDomainForm({ proxyRecordsLoading }: { proxyRecordsLoading: boolean }): JSX.Element {
    return (
        <div className="mt-4 space-y-4">
            <p>
                Ad-blockers can silently drop 10-25% of events. A reverse proxy routes data through your own domain to
                prevent this. We offer a free reverse proxy included with your PostHog account. If you have plans to
                send events to PostHog from the web, we <strong>strongly recommend</strong> you setup a proxy.
                <br />
                <Link to="https://posthog.com/docs/advanced/proxy" target="_blank">
                    You can also set up your own
                </Link>
                .
            </p>

            <Form logic={proxyLogic} formKey="createRecord" enableFormOnSubmit className="space-y-3">
                <LemonField name="domain" label="Domain">
                    <LemonInput autoFocus placeholder="e.g. t.mydomain.com" data-attr="domain-input" />
                </LemonField>
                <p className="text-xs text-secondary">
                    Tip: avoid words like "analytics" or "tracking" in your subdomain — ad-blockers flag them. Use
                    something generic like <code>t.mydomain.com</code>.
                </p>
                <CloudflareDisclosure />
                <div className="flex justify-end">
                    <LemonButton htmlType="submit" type="primary" data-attr="domain-save" loading={proxyRecordsLoading}>
                        Add domain
                    </LemonButton>
                </div>
            </Form>
        </div>
    )
}

function CloudflareDisclosure(): JSX.Element {
    return (
        <LemonCollapse
            panels={[
                {
                    key: 'cloudflare',
                    header: 'Third-party data processing disclosure',
                    content: (
                        <div className="text-xs text-secondary space-y-2">
                            <p>
                                This beta feature routes certain customer and customer end-user traffic through{' '}
                                <Link to="https://www.cloudflare.com" target="_blank">
                                    Cloudflare
                                </Link>
                                , a third-party infrastructure provider, for the purpose of delivering the managed proxy
                                functionality.
                            </p>
                            <p>By adding a domain, you:</p>
                            <ul className="list-disc pl-5 space-y-1">
                                <li>
                                    Explicitly instruct us to route applicable data through Cloudflare for this service;
                                </li>
                                <li>
                                    Acknowledge and agree that data processed as part of this feature will be
                                    transmitted to and processed by Cloudflare; and
                                </li>
                                <li>
                                    Understand that this feature is experimental (beta) and may change or be
                                    discontinued.
                                </li>
                            </ul>
                            <p>
                                Cloudflare is not currently listed as a PostHog subprocessor for this feature, and you
                                choose to enable this feature notwithstanding the foregoing. If we decide to make this
                                functionality generally available, we will update our Data Processing Agreement and
                                provide notice in accordance with its terms.
                            </p>
                        </div>
                    ),
                },
            ]}
        />
    )
}

function WaitingForDns({ records }: { records: ProxyRecord[] }): JSX.Element {
    return (
        <div className="mt-4 space-y-4">
            <p>
                Add this <strong>CNAME</strong> record in your DNS provider:
            </p>
            {records.map((record) => (
                <div key={record.id} className="space-y-2">
                    <div className="flex items-center gap-2">
                        <span className="font-semibold">{record.domain}</span>
                        <Tooltip
                            title={
                                record.status === 'issuing'
                                    ? 'Certificate is being issued'
                                    : 'Waiting for you to add the DNS record'
                            }
                        >
                            <span className="text-warning-dark flex items-center gap-1">
                                <Spinner className="text-sm" />{' '}
                                {record.status === 'issuing' ? 'Issuing certificate' : 'Waiting for DNS'}
                            </span>
                        </Tooltip>
                    </div>
                    <CodeSnippet language={Language.HTTP}>{record.target_cname}</CodeSnippet>
                    <DomainConnectBanner
                        logicKey={`onboarding-proxy-${record.id}`}
                        domain={record.domain}
                        context="proxy"
                        proxyRecordId={record.id}
                    />
                </div>
            ))}
            <p>Once DNS has propagated, update your SDK to route events through your proxy domain.</p>
            <p className="text-xs text-secondary">
                Requests to the proxy domain will fail until DNS propagation completes. It may take a few minutes to
                verify. You can continue with the existing setup and check back in{' '}
                <Link to="/settings/environment/general#managed-reverse-proxy">settings</Link> later.
            </p>
            <ProxySnippet domain={records[0].domain} />
        </div>
    )
}

function ProxyVerified({ record }: { record: ProxyRecord }): JSX.Element {
    return (
        <div className="mt-4 space-y-4">
            <LemonBanner type="success">
                <div className="flex items-center gap-2">
                    <IconCheckCircle className="text-lg" />
                    <span>
                        Your proxy at <strong>{record.domain}</strong> is live.
                    </span>
                </div>
            </LemonBanner>
            <p>Update your SDK to route events through your proxy:</p>
            <ProxySnippet domain={record.domain} />
        </div>
    )
}

function ProxySnippet({ domain }: { domain: string }): JSX.Element {
    const uiHost = apiHostOrigin()
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`posthog.init('<your-project-api-key>', {\n    api_host: 'https://${domain}',\n    ui_host: '${uiHost}',\n})`}
        </CodeSnippet>
    )
}
