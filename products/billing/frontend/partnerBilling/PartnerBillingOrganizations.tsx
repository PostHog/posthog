import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { formatAppliedLimits } from './partnerBillingFormat'
import { partnerBillingInvoicesLogic } from './partnerBillingInvoicesLogic'
import { PartnerBillingLogicProps, partnerBillingLogic } from './partnerBillingLogic'
import { PartnerBillingOrganizationLimitsModal } from './PartnerBillingOrganizationLimitsModal'
import { partnerBillingOrganizationsLogic } from './partnerBillingOrganizationsLogic'
import { partnerBillingTablePagination } from './partnerBillingPagination'

export function PartnerBillingOrganizations({ applicationId }: PartnerBillingLogicProps): JSX.Element {
    const logic = partnerBillingOrganizationsLogic({ applicationId })
    const { organizations, organizationsLoading, organizationsError, organizationsPage } = useValues(logic)
    const { setOrganizationsPage, openOrganizationLimits, loadPartnerBillingOrganizations } = useActions(logic)
    const { limitProductNames, payer } = useValues(partnerBillingLogic({ applicationId }))
    const { showOrganizationInvoices } = useActions(partnerBillingInvoicesLogic({ applicationId }))

    return (
        <section className="flex flex-col gap-4">
            <div>
                <h3 className="text-base font-semibold mb-1">Organizations</h3>
                <p className="text-secondary text-sm mb-0">The PostHog organizations you pay for.</p>
            </div>
            {organizationsError && !organizationsLoading ? (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => loadPartnerBillingOrganizations(),
                        'data-attr': 'partner-billing-reload-organizations',
                    }}
                >
                    {organizationsError}
                </LemonBanner>
            ) : (
                <LemonTable
                    dataSource={organizations?.results ?? []}
                    loading={organizationsLoading}
                    rowKey="organization_id"
                    nouns={['organization', 'organizations']}
                    emptyState="No organizations yet. They appear here when your application creates one for a customer."
                    pagination={partnerBillingTablePagination(
                        organizationsPage,
                        organizations?.count,
                        setOrganizationsPage
                    )}
                    columns={[
                        {
                            title: 'Organization',
                            key: 'organization',
                            render: (_, organization) => (
                                <span className="font-semibold">
                                    {organization.name ?? organization.organization_id}
                                </span>
                            ),
                        },
                        {
                            title: 'Billed to you',
                            key: 'linked',
                            render: (_, organization) =>
                                organization.detached_at ? (
                                    <LemonTag type="muted">
                                        Ended {dayjs(organization.detached_at).format('MMM D, YYYY')}
                                    </LemonTag>
                                ) : organization.linked_at ? (
                                    <span className="whitespace-nowrap">
                                        Since {dayjs(organization.linked_at).format('MMM D, YYYY')}
                                    </span>
                                ) : null,
                        },
                        {
                            title: 'Monthly limits',
                            key: 'limits',
                            render: (_, organization) => {
                                if (organization.detached_at) {
                                    return <span className="text-secondary">Set by the organization</span>
                                }
                                const limits = formatAppliedLimits(
                                    organization.custom_limits_usd,
                                    payer?.default_limits_usd,
                                    limitProductNames
                                )
                                return limits.length > 0 ? (
                                    <div className="flex flex-col">
                                        {limits.map(({ productKey, label }) => (
                                            <span key={productKey}>{label}</span>
                                        ))}
                                    </div>
                                ) : (
                                    <span className="text-secondary">No limits</span>
                                )
                            },
                        },
                        {
                            key: 'actions',
                            render: (_, organization) => (
                                <div className="flex flex-wrap justify-end gap-1">
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        onClick={() => openOrganizationLimits(organization)}
                                        disabledReason={
                                            organization.detached_at
                                                ? 'This organization pays for itself now, so it sets its own limits.'
                                                : undefined
                                        }
                                        data-attr="partner-billing-edit-organization-limits"
                                    >
                                        Edit limits
                                    </LemonButton>
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        onClick={() =>
                                            showOrganizationInvoices({
                                                organizationId: organization.organization_id,
                                                name: organization.name ?? organization.organization_id,
                                            })
                                        }
                                        data-attr="partner-billing-view-organization-invoices"
                                    >
                                        Invoices
                                    </LemonButton>
                                </div>
                            ),
                        },
                    ]}
                />
            )}
            <PartnerBillingOrganizationLimitsModal applicationId={applicationId} />
        </section>
    )
}
