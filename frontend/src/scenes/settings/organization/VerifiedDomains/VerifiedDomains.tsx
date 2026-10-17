import { useActions, useValues } from 'kea'

import { IconInfo, IconLock, IconTrash, IconWarning } from '@posthog/icons'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { RestrictionScope } from 'lib/components/RestrictedArea'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { IconExclamation } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch/LemonSwitch'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { ConfigScopeEnumApi } from '~/generated/core/api.schemas'
import { ProductKey } from '~/queries/schema/schema-general'
import { AvailableFeature, OrganizationDomainType } from '~/types'

import { AddDomainModal } from './AddDomainModal'
import { SSOSelect } from './SSOSelect'
import { verifiedDomainImpactLogic } from './verifiedDomainImpactLogic'
import { RemoveDomainModal } from './VerifiedDomainImpactModals'
import { getIdentityProviderConfigForDomain, verifiedDomainsLogic } from './verifiedDomainsLogic'
import { VerifyDomainModal } from './VerifyDomainModal'

export function VerifiedDomains(): JSX.Element {
    const { verifiedDomainsLoading, updatingDomainLoading } = useValues(verifiedDomainsLogic)
    const { showAddDomainModal } = useActions(verifiedDomainsLogic)

    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })

    return (
        <PayGateMini feature={AvailableFeature.AUTOMATIC_PROVISIONING} featureDetail="verified-domains">
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
        identityProviderConfigsLoading,
        updatingDomainLoading,
        isSSOEnforcementAvailable,
        isOIDCAvailable,
        ownVerifiedDomain,
        identityProviderConfigs,
    } = useValues(verifiedDomainsLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { updateDomain, setVerifyModal } = useActions(verifiedDomainsLogic)
    const { promptRemoveDomain } = useActions(verifiedDomainImpactLogic)
    const { preflight } = useValues(preflightLogic)

    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })

    const verifiedDomainsList = verifiedDomains.filter((d) => d.is_verified)
    const unverifiedDomainsList = verifiedDomains.filter((d) => !d.is_verified)

    // Mirrors the guard on `OrganizationDomainViewSet.destroy`: with the restriction on, an admin
    // can't remove a domain if their own email would be left outside the verified ones.
    const removeBlockedReason = (domain: OrganizationDomainType): string | undefined => {
        if (!currentOrganization?.enforce_verified_domains || !domain.is_verified) {
            return undefined
        }
        return ownVerifiedDomain && ownVerifiedDomain.id !== domain.id
            ? undefined
            : 'Your own email address would no longer be allowed. Turn off the domain restriction first'
    }

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
            render: function SSOEnforcement(_, { sso_enforcement, id }) {
                const hasSaml = Boolean(
                    getIdentityProviderConfigForDomain(identityProviderConfigs, id, ConfigScopeEnumApi.Saml)?.has_saml
                )
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
                        samlAvailable={hasSaml}
                        oidcAvailable={Boolean(
                            isOIDCAvailable &&
                            getIdentityProviderConfigForDomain(identityProviderConfigs, id, ConfigScopeEnumApi.Oidc)
                                ?.has_oidc
                        )}
                        disabledReason={restrictionReason}
                    />
                )
            },
        },
        {
            key: 'actions',
            width: 32,
            align: 'center',
            render: function RenderActions(_, domainRecord) {
                return (
                    <More
                        overlay={
                            <LemonButton
                                status="danger"
                                onClick={() => promptRemoveDomain(domainRecord)}
                                fullWidth
                                icon={<IconTrash />}
                                disabledReason={restrictionReason ?? removeBlockedReason(domainRecord)}
                            >
                                Remove domain
                            </LemonButton>
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
            render: function RenderActions(_, domainRecord) {
                return (
                    <More
                        overlay={
                            <LemonButton
                                status="danger"
                                onClick={() => promptRemoveDomain(domainRecord)}
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
                loading={verifiedDomainsLoading || identityProviderConfigsLoading}
                rowKey="id"
                emptyState="You haven't registered any authentication domains yet."
            />
            {unverifiedDomainsList.length > 0 && (
                <>
                    <h4>Pending domains</h4>
                    <LemonTable
                        dataSource={unverifiedDomainsList}
                        columns={unverifiedColumns}
                        loading={verifiedDomainsLoading || identityProviderConfigsLoading}
                        rowKey="id"
                    />
                </>
            )}
            <AddDomainModal />
            <VerifyDomainModal />
            <RemoveDomainModal />
        </div>
    )
}
