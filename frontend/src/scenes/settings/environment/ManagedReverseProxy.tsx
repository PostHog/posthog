import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconEllipsis, IconInfo } from '@posthog/icons'
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
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { payGateMiniLogic } from 'lib/components/PayGateMini/payGateMiniLogic'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Link } from 'lib/lemon-ui/Link'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { AvailableFeature } from '~/types'

import { ProxyRecord, proxyLogic } from './proxyLogic'

const statusText = {
    valid: 'live',
    timed_out: 'timed out',
}

export function ManagedReverseProxy(): JSX.Element {
    const { cloudflareOptInAcknowledged, formState, proxyRecords, proxyRecordsLoading } = useValues(proxyLogic)
    const { acknowledgeCloudflareOptIn, deleteRecord, showForm } = useActions(proxyLogic)
    const { preflight } = useValues(preflightLogic)

    // Check both instance-level setting AND per-org feature flag
    const instanceCloudflareEnabled = preflight?.instance_preferences?.cloudflare_proxy_enabled
    const orgCloudflareEnabled = useFeatureFlag('MANAGED_PROXY_USE_CLOUDFLARE')
    const cloudflareProxyEnabled = instanceCloudflareEnabled && orgCloudflareEnabled

    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })

    const { featureAvailableOnOrg } = useValues(payGateMiniLogic({ feature: AvailableFeature.MANAGED_REVERSE_PROXY }))

    const maxRecordsReached = proxyRecords.length >= (featureAvailableOnOrg?.limit || 0)

    const recordsWithMessages = proxyRecords.filter((record) => !!record.message)

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
                        <span className="capitalize">{statusText[status] || status}</span>
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
                return (
                    status != 'deleting' &&
                    !restrictionReason && (
                        <LemonMenu
                            items={[
                                {
                                    label: 'Delete',
                                    status: 'danger',
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
    if (cloudflareProxyEnabled && !cloudflareOptInAcknowledged) {
        return (
            <CloudflareOptInBanner onAcknowledge={acknowledgeCloudflareOptIn} restrictionReason={restrictionReason} />
        )
    }

    return (
        <PayGateMini feature={AvailableFeature.MANAGED_REVERSE_PROXY}>
            <div className="deprecated-space-y-2">
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
                    }}
                />
                {formState === 'collapsed' ? (
                    maxRecordsReached ? (
                        <LemonBanner type="info">
                            There is a maximum of {featureAvailableOnOrg?.limit || 0} records allowed per organization.
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
        </PayGateMini>
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
            <div className="text-xl font-semibold leading-tight">Enable Managed Proxy (Beta)</div>
            <p className="text-secondary">
                This feature is disabled by default and has no effect unless you explicitly enable it.
            </p>
            <p>
                By enabling this beta feature, you explicitly instruct us to route applicable traffic via{' '}
                <Link to="https://www.cloudflare.com" target="_blank">
                    Cloudflare
                </Link>
                , and understand that data processed as part of this feature will be transmitted to and processed by
                Cloudflare.
            </p>
            <div className="border rounded p-4 space-y-3 bg-surface-secondary">
                <div className="font-semibold">Third-party processing (Cloudflare)</div>
                <p className="text-sm">
                    This beta feature routes certain customer and customer end-user traffic through Cloudflare, a
                    third-party infrastructure provider, for the purpose of delivering the managed proxy functionality.
                </p>
                <p className="text-sm">By enabling this feature, you:</p>
                <ul className="text-sm list-disc pl-5 space-y-1">
                    <li>Explicitly instruct us to route applicable data through Cloudflare for this service;</li>
                    <li>
                        Acknowledge and agree that data processed as part of this feature will be transmitted to and
                        processed by Cloudflare; and
                    </li>
                    <li>Understand that this feature is experimental (beta) and may change or be discontinued.</li>
                </ul>
                <p className="text-sm">
                    Cloudflare is not currently listed as a PostHog subprocessor for this feature, and you choose to
                    enable this feature notwithstanding the foregoing. If we decide to make this functionality generally
                    available, we will update our Data Processing Agreement and provide notice in accordance with its
                    terms.
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
    return (
        <div className="pb-4 pr-4">
            <LemonTabs
                size="small"
                activeKey="cname"
                tabs={[
                    {
                        label: 'CNAME',
                        key: 'cname',
                        content: (
                            <CodeSnippet key={record.id} language={Language.HTTP}>
                                {record.target_cname}
                            </CodeSnippet>
                        ),
                    },
                ]}
            />
        </div>
    )
}

function CreateRecordForm(): JSX.Element {
    const { formState, proxyRecordsLoading, proxyRecords } = useValues(proxyLogic)
    const { collapseForm } = useActions(proxyLogic)

    const waitingRecords = proxyRecords.filter((r) => r.status === 'waiting')

    return (
        <div className="bg-surface-primary rounded border px-5 py-4 deprecated-space-y-2">
            {formState == 'active' ? (
                <Form
                    logic={proxyLogic}
                    formKey="createRecord"
                    enableFormOnSubmit
                    className="w-full deprecated-space-y-2"
                >
                    <LemonField name="domain">
                        <LemonInput
                            autoFocus
                            placeholder="Enter a domain (e.g. ph.mydomain.com)"
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
            ) : (
                <>
                    <div className="text-xl font-semibold leading-tight">Almost there</div>
                    <div>
                        You need to set the following <b>CNAME</b> records in your DNS provider:
                    </div>
                    {waitingRecords.map((r) => (
                        <div key={r.id} className="deprecated-space-y-1">
                            <span className="font-semibold">{r.domain}</span>
                            <CodeSnippet key={r.id} language={Language.HTTP}>
                                {r.target_cname}
                            </CodeSnippet>
                        </div>
                    ))}
                    <div className="flex justify-end">
                        <LemonButton onClick={collapseForm} type="primary">
                            Done
                        </LemonButton>
                    </div>
                </>
            )}
        </div>
    )
}
