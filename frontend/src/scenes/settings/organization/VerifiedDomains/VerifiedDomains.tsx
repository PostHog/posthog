import { useActions, useValues } from 'kea'

import { IconInfo, IconLock, IconPeople, IconShieldLock, IconShuffle, IconTrash, IconWarning } from '@posthog/icons'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { RestrictionScope } from 'lib/components/RestrictedArea'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { IconExclamation } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch/LemonSwitch'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { AvailableFeature, OrganizationDomainType } from '~/types'

import { AddDomainModal } from './AddDomainModal'
import { ConfigureIdJagModal } from './ConfigureIdJagModal'
import { ConfigureSAMLModal } from './ConfigureSAMLModal'
import { ConfigureSCIMModal } from './ConfigureSCIMModal'
import { ScimLogsModal } from './ScimLogsModal'
import { SSOSelect } from './SSOSelect'
import { verifiedDomainsLogic } from './verifiedDomainsLogic'
import { VerifyDomainModal } from './VerifyDomainModal'

// One distinctive icon per integration type, reused across each integration's status badges.
const SAML_ICON = <IconShieldLock />
const SCIM_ICON = <IconPeople />
const XAA_ICON = <IconShuffle />

function IntegrationBadge({
    label,
    type,
    tooltip,
    icon,
    to,
}: {
    label: string
    type: LemonTagType
    tooltip: string
    icon?: JSX.Element
    to?: string
}): JSX.Element {
    const tag = (
        <LemonTag type={type} icon={icon}>
            {label}
        </LemonTag>
    )
    // The tooltip needs a plain element it can attach hover handlers to; LemonTag can't reliably act as a
    // Base UI tooltip trigger (it would also pick up the injected onClick and look clickable), so wrap it.
    return (
        <Tooltip title={tooltip}>
            {to ? (
                <Link to={to} className="inline-flex">
                    {tag}
                </Link>
            ) : (
                <span className="inline-flex">{tag}</span>
            )}
        </Tooltip>
    )
}

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
        isXAAAuthenticationAvailable,
    } = useValues(verifiedDomainsLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const {
        updateDomain,
        deleteVerifiedDomain,
        setVerifyModal,
        setConfigureSAMLModalId,
        setConfigureSCIMModalId,
        setConfigureIdJagModalId,
        setScimLogsModalId,
    } = useActions(verifiedDomainsLogic)
    const { preflight } = useValues(preflightLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const showXAAControls = !!featureFlags[FEATURE_FLAGS.XAA_AUTHENTICATION] && isXAAAuthenticationAvailable

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
            key: 'integrations',
            title: 'Integrations',
            render: function Integrations(
                _,
                { has_saml, saml_acs_url, saml_entity_id, saml_x509_cert, scim_enabled, has_id_jag }
            ) {
                const billingLink = urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])
                const badges: JSX.Element[] = []

                if (!isSAMLAvailable) {
                    badges.push(
                        <IntegrationBadge
                            key="saml"
                            label="SAML"
                            type="muted"
                            icon={SAML_ICON}
                            tooltip="Upgrade your plan to enable SAML"
                            to={billingLink}
                        />
                    )
                } else if (has_saml) {
                    badges.push(
                        <IntegrationBadge
                            key="saml"
                            label="SAML"
                            type="success"
                            icon={SAML_ICON}
                            tooltip="SAML is enabled"
                        />
                    )
                } else if (saml_acs_url || saml_entity_id || saml_x509_cert) {
                    badges.push(
                        <IntegrationBadge
                            key="saml"
                            label="SAML"
                            type="warning"
                            icon={SAML_ICON}
                            tooltip="SAML is partially configured"
                        />
                    )
                } else {
                    badges.push(
                        <IntegrationBadge
                            key="saml"
                            label="SAML"
                            type="muted"
                            icon={SAML_ICON}
                            tooltip="SAML is not enabled"
                        />
                    )
                }

                if (!isSCIMAvailable) {
                    badges.push(
                        <IntegrationBadge
                            key="scim"
                            label="SCIM"
                            type="muted"
                            icon={SCIM_ICON}
                            tooltip="Upgrade your plan to enable SCIM"
                            to={billingLink}
                        />
                    )
                } else if (scim_enabled) {
                    badges.push(
                        <IntegrationBadge
                            key="scim"
                            label="SCIM"
                            type="success"
                            icon={SCIM_ICON}
                            tooltip="SCIM is enabled"
                        />
                    )
                } else {
                    badges.push(
                        <IntegrationBadge
                            key="scim"
                            label="SCIM"
                            type="muted"
                            icon={SCIM_ICON}
                            tooltip="SCIM is not enabled"
                        />
                    )
                }

                if (showXAAControls && has_id_jag) {
                    badges.push(
                        <IntegrationBadge
                            key="xaa"
                            label="XAA"
                            type="success"
                            icon={XAA_ICON}
                            tooltip="XAA is enabled"
                        />
                    )
                }

                if (badges.length === 0) {
                    return <span className="text-muted">Not configured</span>
                }

                return <div className="flex items-center gap-1 flex-wrap">{badges}</div>
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
                                {showXAAControls && (
                                    <LemonButton
                                        onClick={() => setConfigureIdJagModalId(id)}
                                        fullWidth
                                        disabledReason={restrictionReason}
                                    >
                                        Configure XAA
                                    </LemonButton>
                                )}
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
            {showXAAControls && <ConfigureIdJagModal />}
            <ScimLogsModal />
            <VerifyDomainModal />
        </div>
    )
}
