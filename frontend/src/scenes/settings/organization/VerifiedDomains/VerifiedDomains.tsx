import { useActions, useValues } from 'kea'

import { IconInfo, IconLock, IconTrash, IconWarning } from '@posthog/icons'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { IconExclamation } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch/LemonSwitch'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { OrganizationDomainApi } from '~/generated/core/api.schemas'
import { ProductKey } from '~/queries/schema/schema-general'
import { AvailableFeature, SSOProvider } from '~/types'

import { AddDomainModal } from './AddDomainModal'
import { IdJagSettings } from './IdJagSettings'
import { SAMLSettings } from './SAMLSettings'
import { ScimLogsModal } from './ScimLogsModal'
import { SCIMSettings } from './SCIMSettings'
import { SSOSelect } from './SSOSelect'
import { verifiedDomainsLogic } from './verifiedDomainsLogic'
import { VerifyDomainModal } from './VerifyDomainModal'

export function VerifiedDomains(): JSX.Element {
    const { verifiedDomainsLoading, updatingDomainLoading } = useValues(verifiedDomainsLogic)
    const { showAddDomainModal } = useActions(verifiedDomainsLogic)
    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })

    return (
        <PayGateMini feature={AvailableFeature.AUTOMATIC_PROVISIONING}>
            <div className="space-y-8">
                <section className="space-y-3">
                    <div>
                        <h2>Authentication domains</h2>
                        <p className="text-muted">
                            Verify domains, control automatic provisioning, and choose whether users must sign in with
                            SSO. Identity provider credentials are managed separately below.
                        </p>
                    </div>
                    <DomainsTable />
                    <LemonButton
                        type="primary"
                        onClick={showAddDomainModal}
                        disabledReason={
                            verifiedDomainsLoading || updatingDomainLoading ? 'Loading domains' : restrictionReason
                        }
                    >
                        Add domain
                    </LemonButton>
                </section>
                <SAMLSettings />
                <SCIMSettings />
                <IdJagSettings />
            </div>
            <AddDomainModal />
            <ScimLogsModal />
            <VerifyDomainModal />
        </PayGateMini>
    )
}

function DomainsTable(): JSX.Element {
    const {
        verifiedDomainsList,
        unverifiedDomainsList,
        verifiedDomainsLoading,
        updatingDomainLoading,
        isSSOEnforcementAvailable,
    } = useValues(verifiedDomainsLogic)
    const { updateDomain, deleteVerifiedDomain, setVerifyModal } = useActions(verifiedDomainsLogic)
    const { preflight } = useValues(preflightLogic)
    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })
    const columns: LemonTableColumns<OrganizationDomainApi> = [
        { key: 'domain', title: 'Domain', render: (_, { domain }) => <LemonTag>{domain}</LemonTag> },
        {
            key: 'provisioning',
            title: (
                <div className="flex items-center gap-1">
                    Automatic provisioning
                    <Tooltip title="Allow new users with this email domain to join automatically.">
                        <IconInfo />
                    </Tooltip>
                </div>
            ),
            render: (_, domain) => (
                <LemonSwitch
                    checked={domain.jit_provisioning_enabled ?? false}
                    disabled={updatingDomainLoading}
                    disabledReason={restrictionReason}
                    onChange={(checked) => updateDomain({ id: domain.id, jit_provisioning_enabled: checked })}
                    label="Automatic provisioning"
                />
            ),
        },
        {
            key: 'sso',
            title: 'Enforce SSO',
            render: (_, domain) =>
                isSSOEnforcementAvailable ? (
                    <SSOSelect
                        value={(domain.sso_enforcement || '') as SSOProvider | ''}
                        loading={updatingDomainLoading}
                        onChange={(sso_enforcement) => updateDomain({ id: domain.id, sso_enforcement })}
                        samlAvailable={domain.has_saml}
                        disabledReason={restrictionReason}
                    />
                ) : (
                    <Link
                        to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])}
                        className="flex items-center gap-1"
                    >
                        <IconLock className="text-warning text-lg" /> Upgrade to enable
                    </Link>
                ),
        },
        {
            key: 'actions',
            width: 32,
            render: (_, domain) => (
                <More
                    overlay={
                        <LemonButton
                            fullWidth
                            status="danger"
                            icon={<IconTrash />}
                            disabledReason={restrictionReason}
                            onClick={() =>
                                LemonDialog.open({
                                    title: `Remove ${domain.domain}?`,
                                    description:
                                        'SSO enforcement and automatic provisioning will stop for this domain.',
                                    primaryButton: {
                                        status: 'danger',
                                        children: 'Remove domain',
                                        onClick: () => deleteVerifiedDomain(domain.id),
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }
                        >
                            Remove domain
                        </LemonButton>
                    }
                />
            ),
        },
    ]
    const pendingColumns: LemonTableColumns<OrganizationDomainApi> = [
        { key: 'domain', title: 'Domain', render: (_, { domain }) => <LemonTag>{domain}</LemonTag> },
        ...(preflight?.cloud
            ? ([
                  {
                      key: 'status',
                      title: 'Status',
                      render: (_, domain) =>
                          domain.verified_at ? (
                              <span className="flex items-center gap-1 text-danger">
                                  <IconExclamation /> Verification expired
                              </span>
                          ) : (
                              <span className="flex items-center gap-1 text-warning">
                                  <IconWarning /> Pending verification
                              </span>
                          ),
                  },
              ] as LemonTableColumns<OrganizationDomainApi>)
            : []),
        {
            key: 'verify',
            width: 32,
            render: (_, domain) => (
                <LemonButton type="primary" onClick={() => setVerifyModal(domain.id)}>
                    Verify
                </LemonButton>
            ),
        },
    ]
    return (
        <div className="space-y-3">
            <LemonTable
                dataSource={verifiedDomainsList}
                columns={columns}
                loading={verifiedDomainsLoading}
                rowKey="id"
                emptyState="No verified authentication domains yet."
            />
            {unverifiedDomainsList.length > 0 && (
                <>
                    <h3>Pending domains</h3>
                    <LemonTable dataSource={unverifiedDomainsList} columns={pendingColumns} rowKey="id" />
                </>
            )}
        </div>
    )
}
