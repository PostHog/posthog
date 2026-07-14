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

interface IdentityProviderFeatureCardProps {
    title: string
    description: string
    icon: JSX.Element
    available: boolean
    upgradeUrl: string
    config?: IdentityProviderConfigApi
    domainIds: readonly string[]
    domains: OrganizationDomainApi[]
    ready: boolean
    readyLabel: string
    configureLabel: string
    disabledReason?: string | null
    onConfigure: () => void
    children?: JSX.Element
}

function IdentityProviderFeatureCard({
    title,
    description,
    icon,
    available,
    upgradeUrl,
    config,
    domainIds,
    domains,
    ready,
    readyLabel,
    configureLabel,
    disabledReason,
    onConfigure,
    children,
}: IdentityProviderFeatureCardProps): JSX.Element {
    return (
        <LemonCard className="p-5 flex h-full flex-col gap-4">
            <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2">
                    <span className="text-xl">{icon}</span>
                    <h3>{title}</h3>
                </div>
                <LemonTag type={ready ? 'success' : 'muted'}>
                    {config ? (ready ? readyLabel : 'Needs attention') : 'Not configured'}
                </LemonTag>
            </div>
            <p className="text-muted min-h-10">{description}</p>
            {!available ? (
                <div className="mt-auto">
                    <Link to={upgradeUrl}>Upgrade your plan to configure {title}.</Link>
                </div>
            ) : (
                <>
                    {config ? (
                        <div className="space-y-4">
                            <div>
                                <div className="text-xs font-semibold uppercase text-muted">Configuration</div>
                                <div className="font-semibold">{config.name || title}</div>
                            </div>
                            <div>
                                <div className="mb-1 text-xs font-semibold uppercase text-muted">Domains</div>
                                <DomainTags ids={domainIds} domains={domains} />
                            </div>
                            {children}
                        </div>
                    ) : (
                        <div className="rounded border border-dashed p-3 text-muted">
                            Set up {title} and choose which verified domains should use it.
                        </div>
                    )}
                    <LemonButton
                        className="mt-auto self-start"
                        type={config ? 'secondary' : 'primary'}
                        disabledReason={disabledReason}
                        onClick={onConfigure}
                    >
                        {config ? `Edit ${title}` : configureLabel}
                    </LemonButton>
                </>
            )}
        </LemonCard>
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
    const { setConfigureSAMLModalId, setConfigureSCIMModalId, setConfigureIdJagModalId, setScimLogsModalId } =
        useActions(verifiedDomainsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const billingUrl = urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])
    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })
    const showXAA = !!featureFlags[FEATURE_FLAGS.XAA_AUTHENTICATION] && isXAAAuthenticationAvailable
    const samlConfig = identityProviderConfigs.find(
        (config) =>
            config.saml_domain_ids.length || config.saml_entity_id || config.saml_acs_url || config.saml_x509_cert
    )
    const scimConfig = identityProviderConfigs.find((config) => config.scim_domain_ids.length || config.scim_enabled)
    const xaaConfig = identityProviderConfigs.find(
        (config) => config.id_jag_domain_ids.length || config.id_jag_issuer_url
    )
    return (
        <section className="space-y-4">
            <div>
                <h2>Identity provider settings</h2>
                <p className="text-muted">
                    Configure one connection for each authentication feature, then assign it to any verified domains.
                </p>
            </div>
            <div className={`grid gap-4 ${showXAA ? 'xl:grid-cols-3' : 'lg:grid-cols-2'}`}>
                <IdentityProviderFeatureCard
                    title="SAML"
                    description="Let people sign in through your organization’s identity provider."
                    icon={<IconShieldLock />}
                    available={isSAMLAvailable}
                    upgradeUrl={billingUrl}
                    config={samlConfig}
                    domainIds={samlConfig?.saml_domain_ids || []}
                    domains={verifiedDomainsList}
                    ready={samlConfig?.has_saml || false}
                    readyLabel="Ready"
                    configureLabel="Configure SAML"
                    disabledReason={restrictionReason}
                    onConfigure={() => setConfigureSAMLModalId(samlConfig?.id || NEW_IDENTITY_PROVIDER_CONFIG)}
                />
                <IdentityProviderFeatureCard
                    title="SCIM"
                    description="Provision people and groups from your identity provider."
                    icon={<IconPeople />}
                    available={isSCIMAvailable}
                    upgradeUrl={billingUrl}
                    config={scimConfig}
                    domainIds={scimConfig?.scim_domain_ids || []}
                    domains={verifiedDomainsList}
                    ready={scimConfig?.has_scim || false}
                    readyLabel="Provisioning enabled"
                    configureLabel="Configure SCIM"
                    disabledReason={restrictionReason}
                    onConfigure={() => setConfigureSCIMModalId(scimConfig?.id || NEW_IDENTITY_PROVIDER_CONFIG)}
                >
                    <div className="space-y-2">
                        {scimConfig?.scim_domain_ids.map((id) => {
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
                    </div>
                </IdentityProviderFeatureCard>
                {showXAA && (
                    <IdentityProviderFeatureCard
                        title="XAA"
                        description="Trust identity assertions from external applications and integrations."
                        icon={<IconShuffle />}
                        available={isXAAAuthenticationAvailable}
                        upgradeUrl={billingUrl}
                        config={xaaConfig}
                        domainIds={xaaConfig?.id_jag_domain_ids || []}
                        domains={verifiedDomainsList}
                        ready={xaaConfig?.has_id_jag || false}
                        readyLabel="Ready"
                        configureLabel="Configure XAA"
                        disabledReason={restrictionReason}
                        onConfigure={() => setConfigureIdJagModalId(xaaConfig?.id || NEW_IDENTITY_PROVIDER_CONFIG)}
                    >
                        {xaaConfig?.id_jag_issuer_url ? (
                            <div>
                                <div className="text-xs font-semibold uppercase text-muted">Issuer</div>
                                <div className="truncate font-mono text-sm">{xaaConfig.id_jag_issuer_url}</div>
                            </div>
                        ) : undefined}
                    </IdentityProviderFeatureCard>
                )}
            </div>
        </section>
    )
}
