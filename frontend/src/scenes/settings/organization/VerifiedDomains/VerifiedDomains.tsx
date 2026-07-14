import { useActions, useValues } from 'kea'

import { IconInfo, IconLock, IconPeople, IconShieldLock, IconShuffle, IconTrash, IconWarning } from '@posthog/icons'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { IconExclamation } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch/LemonSwitch'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { IdentityProviderConfigApi, OrganizationDomainApi } from '~/generated/core/api.schemas'
import { ProductKey } from '~/queries/schema/schema-general'
import { AvailableFeature, SSOProvider } from '~/types'

import { AddDomainModal } from './AddDomainModal'
import { ConfigureIdJagModal } from './ConfigureIdJagModal'
import { ConfigureSAMLModal } from './ConfigureSAMLModal'
import { ConfigureSCIMModal } from './ConfigureSCIMModal'
import { ScimLogsModal } from './ScimLogsModal'
import { SSOSelect } from './SSOSelect'
import { NEW_IDENTITY_PROVIDER_CONFIG, verifiedDomainsLogic } from './verifiedDomainsLogic'
import { VerifyDomainModal } from './VerifyDomainModal'

function DomainTags({ ids, domains }: { ids: readonly string[]; domains: OrganizationDomainApi[] }): JSX.Element {
    return ids.length ? (
        <div className="flex flex-wrap gap-1">
            {ids.map((id) => (
                <LemonTag key={id}>{domains.find((domain) => domain.id === id)?.domain || 'Unknown domain'}</LemonTag>
            ))}
        </div>
    ) : (
        <span className="text-muted">No domains assigned</span>
    )
}

function confirmConfigRemoval(config: IdentityProviderConfigApi, onRemove: () => void): void {
    LemonDialog.open({
        title: `Remove ${config.name || 'identity provider configuration'}?`,
        description: 'Authentication and provisioning for its assigned domains will stop immediately.',
        primaryButton: { status: 'danger', children: 'Remove configuration', onClick: onRemove },
        secondaryButton: { children: 'Cancel' },
    })
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
                <IdentityProviderSettings />
            </div>
            <AddDomainModal />
            <ConfigureSAMLModal />
            <ConfigureSCIMModal />
            <ConfigureIdJagModal />
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

function IdentityProviderSettings(): JSX.Element {
    const {
        identityProviderConfigs,
        verifiedDomainsList,
        isSAMLAvailable,
        isSCIMAvailable,
        isXAAAuthenticationAvailable,
    } = useValues(verifiedDomainsLogic)
    const {
        setConfigureSAMLModalId,
        setConfigureSCIMModalId,
        setConfigureIdJagModalId,
        setScimLogsModalId,
        deleteIdentityProviderConfig,
    } = useActions(verifiedDomainsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const billingUrl = urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])
    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })
    const showXAA = !!featureFlags[FEATURE_FLAGS.XAA_AUTHENTICATION] && isXAAAuthenticationAvailable
    const samlConfigs = identityProviderConfigs.filter(
        (config) =>
            config.saml_domain_ids.length || config.saml_entity_id || config.saml_acs_url || config.saml_x509_cert
    )
    const scimConfigs = identityProviderConfigs.filter((config) => config.scim_domain_ids.length || config.scim_enabled)
    const xaaConfigs = identityProviderConfigs.filter(
        (config) => config.id_jag_domain_ids.length || config.id_jag_issuer_url
    )
    const actionsFor = (config: IdentityProviderConfigApi, edit: () => void): JSX.Element => (
        <More
            overlay={
                <>
                    <LemonButton fullWidth onClick={edit}>
                        Edit configuration
                    </LemonButton>
                    <LemonButton
                        fullWidth
                        status="danger"
                        onClick={() => confirmConfigRemoval(config, () => deleteIdentityProviderConfig(config.id))}
                    >
                        Remove configuration
                    </LemonButton>
                </>
            }
        />
    )
    const samlColumns: LemonTableColumns<IdentityProviderConfigApi> = [
        { key: 'name', title: 'Connection', render: (_, config) => config.name || 'Unnamed SAML connection' },
        {
            key: 'status',
            title: 'Status',
            render: (_, config) => (
                <LemonTag type={config.has_saml ? 'success' : 'muted'}>{config.has_saml ? 'Ready' : 'Draft'}</LemonTag>
            ),
        },
        {
            key: 'domains',
            title: 'Domains',
            render: (_, config) => <DomainTags ids={config.saml_domain_ids} domains={verifiedDomainsList} />,
        },
        {
            key: 'actions',
            width: 32,
            render: (_, config) => actionsFor(config, () => setConfigureSAMLModalId(config.id)),
        },
    ]
    const xaaColumns: LemonTableColumns<IdentityProviderConfigApi> = [
        {
            key: 'name',
            title: 'Trust configuration',
            render: (_, config) => config.name || 'Unnamed XAA configuration',
        },
        {
            key: 'issuer',
            title: 'Issuer',
            render: (_, config) => config.id_jag_issuer_url || <span className="text-muted">Not set</span>,
        },
        {
            key: 'domains',
            title: 'Domains',
            render: (_, config) => <DomainTags ids={config.id_jag_domain_ids} domains={verifiedDomainsList} />,
        },
        {
            key: 'actions',
            width: 32,
            render: (_, config) => actionsFor(config, () => setConfigureIdJagModalId(config.id)),
        },
    ]
    return (
        <div className="space-y-8">
            <section className="space-y-3">
                <div className="flex justify-between gap-4">
                    <div>
                        <h2 className="flex items-center gap-2">
                            <IconShieldLock /> SAML
                        </h2>
                        <p className="text-muted">
                            Create reusable SAML connections and assign each one to multiple domains.
                        </p>
                    </div>
                    <LemonButton
                        type="primary"
                        onClick={() => setConfigureSAMLModalId(NEW_IDENTITY_PROVIDER_CONFIG)}
                        disabledReason={restrictionReason || (!isSAMLAvailable ? 'Upgrade to enable SAML' : undefined)}
                    >
                        Add SAML connection
                    </LemonButton>
                </div>
                {isSAMLAvailable ? (
                    <LemonTable
                        dataSource={samlConfigs}
                        columns={samlColumns}
                        rowKey="id"
                        emptyState="No SAML connections yet."
                    />
                ) : (
                    <Link to={billingUrl}>Upgrade your plan to configure SAML.</Link>
                )}
            </section>
            <section className="space-y-3">
                <div className="flex justify-between gap-4">
                    <div>
                        <h2 className="flex items-center gap-2">
                            <IconPeople /> SCIM
                        </h2>
                        <p className="text-muted">
                            Manage provisioning tokens and endpoints independently from domain policy.
                        </p>
                    </div>
                    <LemonButton
                        type="primary"
                        onClick={() => setConfigureSCIMModalId(NEW_IDENTITY_PROVIDER_CONFIG)}
                        disabledReason={restrictionReason || (!isSCIMAvailable ? 'Upgrade to enable SCIM' : undefined)}
                    >
                        Add SCIM configuration
                    </LemonButton>
                </div>
                {!isSCIMAvailable ? (
                    <Link to={billingUrl}>Upgrade your plan to configure SCIM.</Link>
                ) : scimConfigs.length === 0 ? (
                    <LemonCard className="p-4 text-muted">No SCIM provisioning configurations yet.</LemonCard>
                ) : (
                    <div className="grid gap-3 md:grid-cols-2">
                        {scimConfigs.map((config) => (
                            <LemonCard key={config.id} className="p-4 space-y-3">
                                <div className="flex justify-between gap-3">
                                    <div>
                                        <h3>{config.name || 'Unnamed SCIM configuration'}</h3>
                                        <LemonTag type={config.has_scim ? 'success' : 'muted'}>
                                            {config.has_scim ? 'Provisioning enabled' : 'Provisioning disabled'}
                                        </LemonTag>
                                    </div>
                                    {actionsFor(config, () => setConfigureSCIMModalId(config.id))}
                                </div>
                                <DomainTags ids={config.scim_domain_ids} domains={verifiedDomainsList} />
                                {config.scim_domain_ids.map((id) => {
                                    const domain = verifiedDomainsList.find((item) => item.id === id)
                                    return domain?.scim_base_url ? (
                                        <div key={id} className="flex items-center justify-between gap-2">
                                            <span className="truncate font-mono text-sm">{domain.scim_base_url}</span>
                                            <LemonButton size="xsmall" onClick={() => setScimLogsModalId(id)}>
                                                View logs
                                            </LemonButton>
                                        </div>
                                    ) : null
                                })}
                            </LemonCard>
                        ))}
                    </div>
                )}
            </section>
            {showXAA && (
                <section className="space-y-3">
                    <div className="flex justify-between gap-4">
                        <div>
                            <h2 className="flex items-center gap-2">
                                <IconShuffle /> XAA
                            </h2>
                            <p className="text-muted">
                                Define trusted token issuers and reuse them across integration domains.
                            </p>
                        </div>
                        <LemonButton
                            type="primary"
                            onClick={() => setConfigureIdJagModalId(NEW_IDENTITY_PROVIDER_CONFIG)}
                            disabledReason={restrictionReason}
                        >
                            Add XAA configuration
                        </LemonButton>
                    </div>
                    <LemonTable
                        dataSource={xaaConfigs}
                        columns={xaaColumns}
                        rowKey="id"
                        emptyState="No XAA configurations yet."
                    />
                </section>
            )}
        </div>
    )
}
