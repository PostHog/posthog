import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconInfo, IconLock, IconTrash, IconWarning } from '@posthog/icons'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { RestrictionScope } from 'lib/components/RestrictedArea'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { IconExclamation, IconOffline } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch/LemonSwitch'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { AvailableFeature, OrganizationDomainType } from '~/types'

import { AddDomainModal } from './AddDomainModal'
import { ConfigureSAMLModal } from './ConfigureSAMLModal'
import { ConfigureSCIMModal } from './ConfigureSCIMModal'
import { ScimLogsModal } from './ScimLogsModal'
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
            <p>
                Enable users to sign up automatically with an email address on verified domains and enforce SSO for
                accounts under your domains.
            </p>

            <VerifiedDomainsTable />
            <LemonButton
                type="primary"
                onClick={() => showAddDomainModal()}
                className="mt-4"
                disabledReason={verifiedDomainsLoading || updatingDomainLoading ? 'loading...' : restrictionReason}
            >
                Add domain
            </LemonButton>
        </PayGateMini>
    )
}

function VerifiedDomainsTable(): JSX.Element {
    const {
        verifiedDomains,
        verifiedDomainsLoading,
        updatingDomainLoading,
        isSSOEnforcementAvailable,
        isSAMLAvailable,
        isSCIMAvailable,
    } = useValues(verifiedDomainsLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const {
        updateDomain,
        deleteVerifiedDomain,
        setVerifyModal,
        setConfigureSAMLModalId,
        setConfigureSCIMModalId,
        setScimLogsModalId,
    } = useActions(verifiedDomainsLogic)
    const { preflight } = useValues(preflightLogic)

    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })

    const verifiedDomainsList = verifiedDomains.filter((d) => d.is_verified)
    const unverifiedDomainsList = verifiedDomains.filter((d) => !d.is_verified)

    const verifiedColumns: LemonTableColumns<OrganizationDomainType> = [
        {
            key: 'domain',
            title: 'Domain name',
            dataIndex: 'domain',
            render: function RenderDomainName(_, { domain }) {
                return <LemonTag>{domain}</LemonTag>
            },
        },
        {
            key: 'jit_provisioning_enabled',
            title: (
                <div className="flex items-center gap-1">
                    <span>Automatic provisioning</span>
                    <Tooltip
                        title={`Enables just-in-time provisioning. If a user logs in with SSO with an email address on this domain an account will be created in ${
                            currentOrganization?.name || 'this organization'
                        } if it does not exist.`}
                    >
                        <IconInfo />
                    </Tooltip>
                </div>
            ),
            render: function AutomaticProvisioning(_, { jit_provisioning_enabled, id }) {
                return (
                    <div className="flex items-center">
                        <LemonSwitch
                            checked={jit_provisioning_enabled}
                            disabled={updatingDomainLoading}
                            disabledReason={restrictionReason}
                            onChange={(checked) => updateDomain({ id, jit_provisioning_enabled: checked })}
                            label="Automatic provisioning"
                        />
                    </div>
                )
            },
        },
        {
            key: 'sso_enforcement',
            className: 'py-2',
            title: (
                <div className="flex items-center gap-1">
                    <span>Enforce SSO</span>
                    <Tooltip title="Require users with email addresses on this domain to always log in using a specific SSO provider.">
                        <IconInfo />
                    </Tooltip>
                </div>
            ),
            render: function SSOEnforcement(_, { sso_enforcement, id, has_saml }) {
                if (!isSSOEnforcementAvailable) {
                    return (
                        <Link
                            to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])}
                            className="flex items-center gap-1"
                        >
                            <IconLock className="text-warning text-lg" /> Upgrade to enable
                        </Link>
                    )
                }
                return (
                    <SSOSelect
                        value={sso_enforcement}
                        loading={updatingDomainLoading}
                        onChange={(val) => updateDomain({ id, sso_enforcement: val })}
                        samlAvailable={has_saml}
                        disabledReason={restrictionReason}
                    />
                )
            },
        },
        {
            key: 'saml',
            title: 'SAML',
            render: function SAML(_, { saml_acs_url, saml_entity_id, saml_x509_cert, has_saml }) {
                if (!isSAMLAvailable) {
                    return (
                        <Link
                            to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])}
                            className="flex items-center gap-1"
                        >
                            <IconLock className="text-warning text-lg" /> Upgrade to enable
                        </Link>
                    )
                }
                return has_saml ? (
                    <div className="flex items-center gap-1 text-success">
                        <IconCheckCircle className="text-lg pt-0.5" /> SAML enabled
                    </div>
                ) : saml_acs_url || saml_entity_id || saml_x509_cert ? (
                    <div className="flex items-center gap-1 text-warning">
                        <IconWarning className="text-lg pt-0.5" /> SAML partially configured
                    </div>
                ) : (
                    <div className="flex items-center gap-1">
                        <IconOffline className="text-lg" /> SAML not set up
                    </div>
                )
            },
        },
        {
            key: 'scim',
            title: 'SCIM',
            render: function SCIM(_, { scim_enabled }) {
                if (!isSCIMAvailable) {
                    return (
                        <Link
                            to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])}
                            className="flex items-center gap-1"
                        >
                            <IconLock className="text-warning text-lg" /> Upgrade to enable
                        </Link>
                    )
                }
                return scim_enabled ? (
                    <div className="flex items-center gap-1 text-success">
                        <IconCheckCircle className="text-lg pt-0.5" /> SCIM enabled
                    </div>
                ) : (
                    <div className="flex items-center gap-1">
                        <IconOffline className="text-lg" /> SCIM not set up
                    </div>
                )
            },
        },
        {
            key: 'actions',
            width: 32,
            align: 'center',
            render: function RenderActions(_, { id, domain }) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    onClick={() => setConfigureSAMLModalId(id)}
                                    fullWidth
                                    disabledReason={
                                        restrictionReason || (!isSAMLAvailable ? 'Upgrade to enable SAML' : undefined)
                                    }
                                >
                                    Configure SAML
                                </LemonButton>
                                <LemonButton
                                    onClick={() => setConfigureSCIMModalId(id)}
                                    fullWidth
                                    disabledReason={
                                        restrictionReason || (!isSCIMAvailable ? 'Upgrade to enable SCIM' : undefined)
                                    }
                                >
                                    Configure SCIM
                                </LemonButton>
                                {isSCIMAvailable && (
                                    <LemonButton
                                        onClick={() => setScimLogsModalId(id)}
                                        fullWidth
                                        disabledReason={restrictionReason}
                                    >
                                        View SCIM logs
                                    </LemonButton>
                                )}
                                <LemonButton
                                    status="danger"
                                    onClick={() =>
                                        LemonDialog.open({
                                            title: `Remove ${domain}?`,
                                            description:
                                                'This cannot be undone. If you have SAML configured or SSO enforced, it will be immediately disabled.',
                                            primaryButton: {
                                                status: 'danger',
                                                children: 'Remove domain',
                                                onClick: () => deleteVerifiedDomain(id),
                                            },
                                            secondaryButton: {
                                                children: 'Cancel',
                                            },
                                        })
                                    }
                                    fullWidth
                                    icon={<IconTrash />}
                                    disabledReason={restrictionReason}
                                >
                                    Remove domain
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    const unverifiedColumns: LemonTableColumns<OrganizationDomainType> = [
        {
            key: 'domain',
            title: 'Domain name',
            dataIndex: 'domain',
            render: function RenderDomainName(_, { domain }) {
                return <LemonTag>{domain}</LemonTag>
            },
        },
        ...(preflight?.cloud
            ? ([
                  {
                      key: 'is_verified',
                      title: 'Status',
                      render: function Verified(_, { verified_at }) {
                          return verified_at ? (
                              <div className="flex items-center gap-1 text-danger">
                                  <IconExclamation className="text-lg" /> Verification expired
                              </div>
                          ) : (
                              <div className="flex items-center gap-1 text-warning">
                                  <IconWarning className="text-lg" /> Pending verification
                              </div>
                          )
                      },
                  },
              ] as LemonTableColumns<OrganizationDomainType>)
            : []),
        {
            key: 'verify',
            className: 'py-2',
            width: 32,
            align: 'center',
            render: function RenderVerify(_, { id }) {
                return (
                    <LemonButton type="primary" onClick={() => setVerifyModal(id)} disabledReason={restrictionReason}>
                        Verify
                    </LemonButton>
                )
            },
        },
        {
            key: 'actions',
            width: 32,
            align: 'center',
            render: function RenderActions(_, { id, domain }) {
                return (
                    <More
                        overlay={
                            <LemonButton
                                status="danger"
                                onClick={() =>
                                    LemonDialog.open({
                                        title: `Remove ${domain}?`,
                                        description: 'This cannot be undone.',
                                        primaryButton: {
                                            status: 'danger',
                                            children: 'Remove domain',
                                            onClick: () => deleteVerifiedDomain(id),
                                        },
                                        secondaryButton: {
                                            children: 'Cancel',
                                        },
                                    })
                                }
                                fullWidth
                                icon={<IconTrash />}
                                disabledReason={restrictionReason}
                            >
                                Remove domain
                            </LemonButton>
                        }
                    />
                )
            },
        },
    ]

    return (
        <div className="space-y-4">
            <LemonTable
                dataSource={verifiedDomainsList}
                columns={verifiedColumns}
                loading={verifiedDomainsLoading}
                rowKey="id"
                emptyState="You haven't registered any authentication domains yet."
            />
            {unverifiedDomainsList.length > 0 && (
                <>
                    <h4>Pending domains</h4>
                    <LemonTable
                        dataSource={unverifiedDomainsList}
                        columns={unverifiedColumns}
                        loading={verifiedDomainsLoading}
                        rowKey="id"
                    />
                </>
            )}
            <AddDomainModal />
            <ConfigureSAMLModal />
            <ConfigureSCIMModal />
            <ScimLogsModal />
            <VerifyDomainModal />
        </div>
    )
}
