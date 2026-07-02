import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useMemo } from 'react'

import { IconCheckCircle, IconEllipsis, IconInfo, IconWarning, IconX } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonDialog,
    LemonInput,
    LemonMenu,
    LemonTable,
    LemonTableColumns,
    LemonTabs,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { DomainConnectBanner } from 'lib/components/DomainConnect'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Link } from 'lib/lemon-ui/Link'
import { isKeyOf } from 'lib/utils/guards'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { DiagnosticCheckResult, DiagnosticCheckStatus, DiagnosticReport, ProxyRecord, proxyLogic } from './proxyLogic'
import { ProxySDKSetup } from './ProxySDKSetup'

const statusText = {
    valid: 'live',
    timed_out: 'timed out',
}

export function ManagedReverseProxy(): JSX.Element {
    const {
        shouldShowCloudflareOptIn,
        formState,
        proxyRecords,
        proxyRecordsLoading,
        maxProxyRecords,
        diagnoseLoadingIds,
        expandedRecordIds,
    } = useValues(proxyLogic)
    const { acknowledgeCloudflareOptIn, deleteRecord, retryRecord, diagnose, setRecordExpanded, showForm } =
        useActions(proxyLogic)
    const { preflight } = useValues(preflightLogic)

    const cloudflareProxyEnabled = preflight?.instance_preferences?.cloudflare_proxy_enabled

    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })

    const maxRecordsReached = proxyRecords.length >= maxProxyRecords

    const recordsWithMessages = proxyRecords.filter((record) => !!record.message)
    const validProxyRecords = proxyRecords.filter((record) => record.status === 'valid')

    // Surface the diagnose_proxy MaxTool while this scene is mounted, with the visible
    // records as context so Max can resolve "diagnose e.foo.com" to a record id.
    useMaxTool({
        identifier: 'diagnose_proxy',
        active: proxyRecords.length > 0 && !restrictionReason,
        context: useMemo(
            () => ({
                proxy_records: proxyRecords.map((r) => ({
                    id: r.id,
                    domain: r.domain,
                    status: r.status,
                    message: r.message,
                })),
            }),
            [proxyRecords]
        ),
        suggestions: useMemo(() => {
            const erroring = proxyRecords.find((r) => r.status === 'erroring' || r.status === 'timed_out')
            if (erroring) {
                return [`Why is ${erroring.domain} erroring?`]
            }
            return proxyRecords.length > 0 ? [`Diagnose ${proxyRecords[0].domain}`] : []
        }, [proxyRecords]),
    })

    const columns: LemonTableColumns<ProxyRecord> = [
        {
            title: 'Domain',
            dataIndex: 'domain',
        },
        {
            title: 'Status',
            dataIndex: 'status',
            render: function RenderStatus(status) {
                if (!status) {
                    return <span>Unknown</span>
                }

                return (
                    <div
                        className={clsx(
                            'deprecated-space-x-1',
                            status === 'valid'
                                ? 'text-success'
                                : status == 'erroring'
                                  ? 'text-danger'
                                  : 'text-warning-dark'
                        )}
                    >
                        {status === 'issuing' && <Spinner />}
                        <span className="capitalize">{isKeyOf(status, statusText) ? statusText[status] : status}</span>
                        {status === 'waiting' && (
                            <Tooltip title="Waiting for DNS records to be created">
                                <IconInfo className="cursor-pointer" />
                            </Tooltip>
                        )}
                        {status === 'timed_out' && (
                            <Tooltip title="Timed out waiting for DNS records to be created. Please delete the record and try again">
                                <IconInfo className="cursor-pointer" />
                            </Tooltip>
                        )}
                    </div>
                )
            },
        },
        {
            title: <span className="h-5" />,
            width: 20,
            className: 'flex justify-center',
            render: function Render(_, { id, status }) {
                const isDiagnosing = diagnoseLoadingIds.includes(id)
                return (
                    status != 'deleting' &&
                    !restrictionReason && (
                        <LemonMenu
                            items={[
                                {
                                    label: isDiagnosing ? 'Running diagnostics…' : 'Diagnose',
                                    onClick: () => diagnose(id),
                                    disabledReason: isDiagnosing ? 'A diagnostic is already running' : undefined,
                                },
                                ...(status === 'erroring' || status === 'timed_out'
                                    ? [
                                          {
                                              label: 'Retry',
                                              onClick: () => retryRecord(id),
                                          },
                                      ]
                                    : []),
                                {
                                    label: 'Delete',
                                    status: 'danger' as const,
                                    onClick: () => {
                                        LemonDialog.open({
                                            title: 'Delete managed proxy',
                                            width: '20rem',
                                            content:
                                                'Are you sure you want to delete this managed proxy? This cannot be undone and if it is in use then events sent to the domain will not be processed.',
                                            primaryButton: {
                                                status: 'danger',
                                                onClick: () => deleteRecord(id),
                                                children: 'Delete',
                                            },
                                            secondaryButton: {
                                                children: 'Cancel',
                                            },
                                        })
                                    },
                                },
                            ]}
                        >
                            <LemonButton size="small" icon={<IconEllipsis className="text-secondary" />} />
                        </LemonMenu>
                    )
                )
            },
        },
    ]

    // Show opt-in banner if Cloudflare proxy is enabled but not yet acknowledged
    if (cloudflareProxyEnabled && shouldShowCloudflareOptIn) {
        return (
            <CloudflareOptInBanner onAcknowledge={acknowledgeCloudflareOptIn} restrictionReason={restrictionReason} />
        )
    }

    return (
        <div className="flex flex-col gap-2">
            {recordsWithMessages.map((r) => (
                <LemonBanner type="warning" key={r.id}>
                    <LemonMarkdown>{`**${r.domain}**\n ${r.message}`}</LemonMarkdown>
                </LemonBanner>
            ))}
            <LemonTable
                loading={proxyRecords.length === 0 && proxyRecordsLoading}
                columns={columns}
                dataSource={proxyRecords}
                expandable={{
                    expandedRowRender: (record) => <ExpandedRow record={record} />,
                    isRowExpanded: (record) => (expandedRecordIds.includes(record.id) ? true : -1),
                    onRowExpand: (record) => setRecordExpanded(record.id, true),
                    onRowCollapse: (record) => setRecordExpanded(record.id, false),
                }}
            />

            <WaitingRecords />

            {validProxyRecords.length > 0 && (
                <div className="flex flex-col gap-2 bg-surface-primary rounded border my-4 px-5 py-4">
                    <div className="text-xl font-semibold leading-tight">Update your SDK configuration</div>
                    <p className="text-secondary">
                        Now that your proxy is live, update your SDK initialization to send data through your custom
                        domain.
                    </p>
                    <ProxySDKSetup />
                </div>
            )}

            {formState === 'collapsed' ? (
                maxRecordsReached ? (
                    <LemonBanner type="info">
                        There is a maximum of {maxProxyRecords} proxy records allowed per organization.
                    </LemonBanner>
                ) : (
                    <div className="flex">
                        <LemonButton onClick={showForm} type="primary" disabledReason={restrictionReason}>
                            Add managed proxy
                        </LemonButton>
                    </div>
                )
            ) : (
                <CreateRecordForm />
            )}
        </div>
    )
}

function CloudflareOptInBanner({
    onAcknowledge,
    restrictionReason,
}: {
    onAcknowledge: () => void
    restrictionReason: string | false | undefined | null
}): JSX.Element {
    const { cloudflareOptInChecked } = useValues(proxyLogic)
    const { setCloudflareOptInChecked } = useActions(proxyLogic)

    return (
        <div className="bg-surface-primary rounded border px-5 py-4 space-y-4">
            <div className="text-xl font-semibold leading-tight">Enable Managed Proxy</div>
            <p className="text-secondary">
                This feature is disabled by default and has no effect unless you explicitly enable it.
            </p>
            <p>
                By enabling this feature, you explicitly instruct us to route applicable traffic via{' '}
                <Link to="https://www.cloudflare.com" target="_blank">
                    Cloudflare
                </Link>
                , and understand that data processed as part of this feature will be transmitted to and processed by
                Cloudflare.
            </p>
            <div className="border rounded p-4 space-y-3 bg-surface-secondary">
                <div className="font-semibold">Third-party processing (Cloudflare)</div>
                <p className="text-sm">
                    This feature routes certain customer and customer end-user traffic through Cloudflare, a third-party
                    infrastructure provider, for the purpose of delivering the managed proxy functionality. Cloudflare
                    is listed as a{' '}
                    <Link to="https://posthog.com/subprocessors" target="_blank">
                        subprocessor
                    </Link>{' '}
                    referenced in our{' '}
                    <Link to="https://posthog.com/dpa" target="_blank">
                        Data Processing Agreement
                    </Link>{' '}
                    ("<strong>DPA</strong>") for this purpose.
                </p>
                <p className="text-sm">By enabling this feature, you:</p>
                <ul className="text-sm list-disc pl-5 space-y-1">
                    <li>Explicitly instruct us to route applicable data through Cloudflare for this service;</li>
                    <li>
                        Acknowledge and agree that data processed as part of this feature will be transmitted to and
                        processed by Cloudflare, and that this processing may occur using Cloudflare infrastructure in
                        multiple or dynamically assigned geographic locations as part of providing managed reverse proxy
                        functionality, in accordance with our DPA; and
                    </li>
                    <li>
                        Understand that traffic routed through this proxy is handled by Cloudflare as described in our
                        DPA.
                    </li>
                </ul>
            </div>
            <div className="border rounded p-4 space-y-3 bg-surface-secondary">
                <div className="font-semibold">HIPAA Disclaimer</div>
                <p className="text-sm">
                    This feature is not HIPAA-compliant and is not intended for the processing of Protected Health
                    Information ("<strong>PHI</strong>"). Any Business Associate Agreement ("<strong>BAA</strong>") you
                    may have entered into with PostHog does not apply to this functionality. You agree not to use this
                    feature with PHI.
                </p>
            </div>
            <div className="space-y-3">
                <LemonCheckbox
                    checked={cloudflareOptInChecked}
                    onChange={setCloudflareOptInChecked}
                    label="I have read and agree to the above terms"
                />
                <LemonButton
                    type="primary"
                    onClick={onAcknowledge}
                    disabled={!cloudflareOptInChecked}
                    disabledReason={
                        restrictionReason || (!cloudflareOptInChecked ? 'You must agree to the terms' : undefined)
                    }
                >
                    Enable Managed Proxy
                </LemonButton>
            </div>
        </div>
    )
}

const ExpandedRow = ({ record }: { record: ProxyRecord }): JSX.Element => {
    const { diagnosticReports, recordActiveTabs } = useValues(proxyLogic)
    const { setRecordActiveTab } = useActions(proxyLogic)

    const report = diagnosticReports[record.id]
    const activeKey = recordActiveTabs[record.id] ?? 'cname'

    const tabs = [
        {
            label: 'CNAME',
            key: 'cname',
            content: (
                <CodeSnippet key={record.id} language={Language.HTTP}>
                    {record.target_cname}
                </CodeSnippet>
            ),
        },
        ...(report
            ? [
                  {
                      label: 'Diagnosis',
                      key: 'diagnosis',
                      content: <DiagnosticReportContent report={report} record={record} />,
                  },
              ]
            : []),
    ]

    return (
        <div className="pb-4 pr-4 space-y-2">
            <LemonTabs
                size="small"
                activeKey={activeKey}
                onChange={(key) => setRecordActiveTab(record.id, key)}
                tabs={tabs}
            />
            {record.status === 'waiting' && (
                <DomainConnectBanner
                    logicKey={`proxy-${record.id}`}
                    domain={record.domain}
                    context="proxy"
                    proxyRecordId={record.id}
                />
            )}
        </div>
    )
}

function CreateRecordForm(): JSX.Element {
    const { formState, proxyRecordsLoading } = useValues(proxyLogic)
    const { collapseForm } = useActions(proxyLogic)

    return (
        <div className="bg-surface-primary rounded border px-5 py-4 deprecated-space-y-2">
            {formState == 'active' && (
                <Form
                    logic={proxyLogic}
                    formKey="createRecord"
                    enableFormOnSubmit
                    className="w-full deprecated-space-y-2"
                >
                    <LemonBanner type="warning">
                        <p className="font-semibold mb-1">
                            Avoid domains that ad-blockers may flag as analytics or advertising related.
                        </p>
                        <ul className="list-disc pl-5 space-y-0.5 mb-1">
                            <li>
                                <strong>Do not use</strong> subdomains containing words related to tracking, analytics,
                                advertising, or PostHog (e.g. <code>analytics.mydomain.com</code>,{' '}
                                <code>posthog.mydomain.com</code>, or <code>ph.mydomain.com</code>). These are commonly
                                blocked by ad-blockers and will cause data loss. The proxy will <strong>NOT</strong>{' '}
                                achieve the intended effect if ad-blockers are blocking the domain.
                            </li>
                            <li>
                                <strong>Use a generic subdomain</strong> such as <code>t.mydomain.com</code> instead.
                            </li>
                        </ul>
                    </LemonBanner>
                    <LemonField name="domain" label="Domain">
                        <LemonInput
                            autoFocus
                            placeholder="Enter a domain (e.g. t.mydomain.com)"
                            data-attr="domain-input"
                        />
                    </LemonField>
                    <div className="flex justify-end gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={collapseForm}
                            disabledReason={proxyRecordsLoading ? 'Saving' : undefined}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            htmlType="submit"
                            type="primary"
                            data-attr="domain-save"
                            loading={proxyRecordsLoading}
                        >
                            Add
                        </LemonButton>
                    </div>
                </Form>
            )}
        </div>
    )
}

const WaitingRecords = (): JSX.Element | null => {
    const { proxyRecords } = useValues(proxyLogic)

    const waitingRecords = proxyRecords.filter((r) => r.status === 'waiting')

    if (waitingRecords.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2 bg-surface-primary rounded border px-5 py-4">
            <div className="text-xl font-semibold leading-tight">Almost there</div>
            <div>
                You need to set the following <b>CNAME</b> records in your DNS provider:
            </div>
            <div className="flex flex-col gap-1">
                {waitingRecords.map((r) => (
                    <div key={r.id}>
                        <span className="font-semibold">{r.domain}</span>
                        <CodeSnippet key={r.id} language={Language.HTTP}>
                            {r.target_cname}
                        </CodeSnippet>

                        <DomainConnectBanner
                            logicKey={`proxy-${r.id}`}
                            domain={r.domain}
                            context="proxy"
                            proxyRecordId={r.id}
                            className="mt-2"
                        />
                    </div>
                ))}
            </div>
            <div className="text-sm">
                <strong>Important:</strong> If you are using a DNS provider like Cloudflare that offers proxy options
                (orange cloud), make sure the proxy is <strong>disabled</strong> (gray cloud) for this domain. Enabling
                the proxy at your DNS provider may interfere with the managed reverse proxy functionality.
            </div>
        </div>
    )
}

const checkStatusIcon = (status: DiagnosticCheckStatus): JSX.Element => {
    switch (status) {
        case 'passed':
            return <IconCheckCircle className="text-success" />
        case 'warned':
            return <IconWarning className="text-warning-dark" />
        case 'failed':
            return <IconX className="text-danger" />
        case 'skipped':
            return <IconInfo className="text-secondary" />
    }
}

function DiagnosticReportContent({ report, record }: { report: DiagnosticReport; record: ProxyRecord }): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <div className="text-xs text-secondary">Ran {new Date(report.ran_at).toLocaleString()}</div>
            <div className="flex flex-col gap-2">
                {report.checks.map((check) => (
                    <DiagnosticCheckRow key={check.id} check={check} record={record} />
                ))}
            </div>
        </div>
    )
}

// A proxy that's provisioning or being torn down can't be retried — mirror the backend guard so the
// button can't kick off a workflow that would race the in-flight one.
const RETRY_BLOCKING_STATUSES: ProxyRecord['status'][] = ['waiting', 'issuing', 'deleting']

function DiagnosticCheckRow({ check, record }: { check: DiagnosticCheckResult; record: ProxyRecord }): JSX.Element {
    const { retryRecord } = useActions(proxyLogic)
    const retryBlocked = RETRY_BLOCKING_STATUSES.includes(record.status)

    return (
        <div className="border rounded p-3 flex flex-col gap-2 bg-surface-secondary">
            <div className="flex items-center gap-2">
                {checkStatusIcon(check.status)}
                <span className="font-semibold">{check.name}</span>
                <span className="text-xs text-secondary capitalize">({check.status})</span>
            </div>
            <LemonMarkdown className="text-sm">{check.detail}</LemonMarkdown>
            {check.remediation && (
                <div className="border-t pt-2 mt-1 flex flex-col gap-2">
                    <LemonMarkdown className="text-sm font-semibold">{check.remediation.summary}</LemonMarkdown>
                    {check.remediation.records.length > 0 && (
                        <div className="flex flex-col gap-1">
                            {check.remediation.records.map((dnsRecord, i) => (
                                <CodeSnippet key={i} language={Language.HTTP}>
                                    {`${dnsRecord.name}\t${dnsRecord.type}\t${dnsRecord.value}`}
                                </CodeSnippet>
                            ))}
                        </div>
                    )}
                    {check.remediation.type === 'retry' && (
                        <div>
                            <LemonButton
                                type="secondary"
                                size="small"
                                loading={retryBlocked}
                                disabledReason={retryBlocked ? 'A retry is already in progress' : undefined}
                                onClick={() => retryRecord(record.id)}
                            >
                                Retry
                            </LemonButton>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
