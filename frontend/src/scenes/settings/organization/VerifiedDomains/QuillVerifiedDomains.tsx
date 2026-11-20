import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'

import { IconEllipsis, IconInfo, IconLock, IconTrash, IconWarning } from '@posthog/icons'
import {
    Badge,
    Button,
    DataTable,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Heading,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { IconExclamation } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'
import { urls } from 'scenes/urls'

import { ConfigScopeEnumApi } from '~/generated/core/api.schemas'
import { ProductKey } from '~/queries/schema/schema-general'
import { AvailableFeature, OrganizationDomainType } from '~/types'

import { AddDomainModal } from './AddDomainModal'
import { ConfigureIdJagModal } from './ConfigureIdJagModal'
import { ConfigureSAMLModal } from './ConfigureSAMLModal'
import { ConfigureSCIMModal } from './ConfigureSCIMModal'
import { QuillSSOSelect } from './QuillSSOSelect'
import { removeDomainBlockedReason } from './removeDomainBlockedReason'
import { ScimLogsModal } from './ScimLogsModal'
import { verifiedDomainImpactLogic } from './verifiedDomainImpactLogic'
import { RemoveDomainModal } from './VerifiedDomainImpactModals'
import { VerifiedDomainIntegrations } from './VerifiedDomainIntegrations'
import { getIdentityProviderConfigForDomain, verifiedDomainsLogic } from './verifiedDomainsLogic'
import { VerifyDomainModal } from './VerifyDomainModal'

function HeaderWithHelp({ label, help }: { label: string; help: string }): JSX.Element {
    return (
        <span className="flex items-center gap-1">
            {label}
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={<Button size="icon-xs" aria-label={`About ${label.toLowerCase()}`} />}
                >
                    <IconInfo />
                </TooltipTrigger>
                <TooltipContent className="max-w-80">{help}</TooltipContent>
            </Tooltip>
        </span>
    )
}

export function QuillVerifiedDomains(): JSX.Element {
    const {
        verifiedDomains,
        verifiedDomainsLoading,
        identityProviderConfigsLoading,
        updatingDomainLoading,
        isSSOEnforcementAvailable,
        isSAMLAvailable,
        isOIDCAvailable,
        isSCIMAvailable,
        isXAAAuthenticationAvailable,
        ownVerifiedDomain,
        identityProviderConfigs,
    } = useValues(verifiedDomainsLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const {
        showAddDomainModal,
        updateDomain,
        setVerifyModal,
        setConfigureSAMLModalId,
        setConfigureSCIMModalId,
        setConfigureIdJagModalId,
        setScimLogsModalId,
    } = useActions(verifiedDomainsLogic)
    const { promptRemoveDomain } = useActions(verifiedDomainImpactLogic)
    const { preflight } = useValues(preflightLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })

    const showXAAControls = !!featureFlags[FEATURE_FLAGS.XAA_AUTHENTICATION] && isXAAAuthenticationAvailable
    const isSSOSettingsRedesignEnabled = !!featureFlags[FEATURE_FLAGS.SSO_SETTINGS_REDESIGN]
    const loading = verifiedDomainsLoading || identityProviderConfigsLoading
    const verifiedDomainsList = verifiedDomains.filter((d) => d.is_verified)
    const unverifiedDomainsList = verifiedDomains.filter((d) => !d.is_verified)

    const domainColumn: ColumnDef<OrganizationDomainType> = {
        id: 'domain',
        header: 'Domain name',
        cell: ({ row }) => <Badge>{row.original.domain}</Badge>,
    }

    const verifiedColumns: ColumnDef<OrganizationDomainType>[] = [
        domainColumn,
        {
            id: 'jit_provisioning_enabled',
            header: () => (
                <HeaderWithHelp
                    label="Automatic provisioning"
                    help={`Enables just-in-time provisioning. If a user logs in with SSO with an email address on this domain an account will be created in ${
                        currentOrganization?.name || 'this organization'
                    } if it does not exist.`}
                />
            ),
            cell: ({ row }) => (
                <QuillSettingSwitch
                    label="Automatic provisioning"
                    checked={row.original.jit_provisioning_enabled}
                    disabled={updatingDomainLoading}
                    disabledReason={restrictionReason}
                    onCheckedChange={(checked) =>
                        updateDomain({ id: row.original.id, jit_provisioning_enabled: checked })
                    }
                />
            ),
        },
        {
            id: 'sso_enforcement',
            header: () => (
                <HeaderWithHelp
                    label="Enforce SSO"
                    help="Require users with email addresses on this domain to always log in using a specific SSO provider."
                />
            ),
            cell: ({ row }) => {
                const { id, sso_enforcement } = row.original

                if (!isSSOEnforcementAvailable) {
                    return (
                        <Button
                            variant="link-foreground"
                            size="sm"
                            nativeButton={false}
                            render={<LinkPrimitive to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])} />}
                        >
                            <IconLock className="text-warning-foreground" />
                            Upgrade to enable
                        </Button>
                    )
                }

                return (
                    <QuillSSOSelect
                        value={sso_enforcement}
                        loading={updatingDomainLoading}
                        onChange={(val) => updateDomain({ id, sso_enforcement: val })}
                        samlAvailable={Boolean(
                            getIdentityProviderConfigForDomain(identityProviderConfigs, id, ConfigScopeEnumApi.Saml)
                                ?.has_saml
                        )}
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
        ...(isSSOSettingsRedesignEnabled
            ? []
            : [
                  {
                      id: 'integrations',
                      header: 'Integrations',
                      cell: ({ row }: { row: { original: OrganizationDomainType } }) => (
                          <VerifiedDomainIntegrations id={row.original.id} />
                      ),
                  },
              ]),
        {
            id: 'actions',
            header: '',
            meta: { align: 'right' },
            cell: ({ row }) => {
                const domainRecord = row.original
                const { id } = domainRecord

                return (
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    size="icon"
                                    aria-label={`Actions for ${domainRecord.domain}`}
                                    tooltip={`Actions for ${domainRecord.domain}`}
                                />
                            }
                        >
                            <IconEllipsis />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                            {!isSSOSettingsRedesignEnabled && (
                                <>
                                    <DropdownMenuItem
                                        onClick={() => setConfigureSAMLModalId(id)}
                                        disabledReason={
                                            restrictionReason ||
                                            (!isSAMLAvailable ? 'Upgrade to enable SAML' : undefined)
                                        }
                                    >
                                        Configure SAML
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                        onClick={() => setConfigureSCIMModalId(id)}
                                        disabledReason={
                                            restrictionReason ||
                                            (!isSCIMAvailable ? 'Upgrade to enable SCIM' : undefined)
                                        }
                                    >
                                        Configure SCIM
                                    </DropdownMenuItem>
                                    {showXAAControls && (
                                        <DropdownMenuItem
                                            onClick={() => setConfigureIdJagModalId(id)}
                                            disabledReason={restrictionReason}
                                        >
                                            Configure XAA
                                        </DropdownMenuItem>
                                    )}
                                    {isSCIMAvailable && (
                                        <DropdownMenuItem
                                            onClick={() => setScimLogsModalId(id)}
                                            disabledReason={restrictionReason}
                                        >
                                            View SCIM logs
                                        </DropdownMenuItem>
                                    )}
                                </>
                            )}
                            <DropdownMenuItem
                                variant="destructive"
                                onClick={() => promptRemoveDomain(domainRecord)}
                                disabledReason={
                                    restrictionReason ??
                                    removeDomainBlockedReason(domainRecord, currentOrganization, ownVerifiedDomain)
                                }
                            >
                                <IconTrash />
                                Remove domain
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                )
            },
        },
    ]

    const unverifiedColumns: ColumnDef<OrganizationDomainType>[] = [
        domainColumn,
        ...(preflight?.cloud
            ? [
                  {
                      id: 'is_verified',
                      header: 'Status',
                      cell: ({ row }: { row: { original: OrganizationDomainType } }) =>
                          row.original.verified_at ? (
                              <Badge variant="destructive">
                                  <IconExclamation />
                                  Verification expired
                              </Badge>
                          ) : (
                              <Badge variant="warning">
                                  <IconWarning />
                                  Pending verification
                              </Badge>
                          ),
                  },
              ]
            : []),
        {
            id: 'verify',
            header: '',
            meta: { align: 'right' },
            cell: ({ row }) => (
                <div className="flex items-center justify-end gap-1">
                    <Button
                        variant="primary"
                        onClick={() => setVerifyModal(row.original.id)}
                        disabledReason={restrictionReason}
                    >
                        Verify
                    </Button>
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    size="icon"
                                    aria-label={`Actions for ${row.original.domain}`}
                                    tooltip={`Actions for ${row.original.domain}`}
                                />
                            }
                        >
                            <IconEllipsis />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                            <DropdownMenuItem
                                variant="destructive"
                                onClick={() => promptRemoveDomain(row.original)}
                                disabledReason={restrictionReason}
                            >
                                <IconTrash />
                                Remove domain
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                </div>
            ),
        },
    ]

    return (
        <PayGateMini feature={AvailableFeature.AUTOMATIC_PROVISIONING} featureDetail="verified-domains">
            <div className="flex flex-col gap-2">
                <Text size="xs" render={<p className="m-0" />}>
                    Enable users to sign up automatically with an email address on verified domains and enforce SSO for
                    accounts under your domains.
                </Text>
                {loading && verifiedDomains.length === 0 ? (
                    <Skeleton className="h-24 w-full" />
                ) : (
                    <DataTable
                        columns={verifiedColumns}
                        data={verifiedDomainsList}
                        getRowId={(domain) => domain.id}
                        fullWidth
                        empty={
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                You haven't registered any authentication domains yet.
                            </Text>
                        }
                    />
                )}
                {unverifiedDomainsList.length > 0 && (
                    <>
                        <Heading size="sm" render={<h3 className="m-0" />}>
                            Pending domains
                        </Heading>
                        <DataTable
                            columns={unverifiedColumns}
                            data={unverifiedDomainsList}
                            getRowId={(domain) => domain.id}
                            fullWidth
                        />
                    </>
                )}
                <div className="flex">
                    <Button
                        variant="primary"
                        onClick={() => showAddDomainModal()}
                        disabledReason={
                            verifiedDomainsLoading || updatingDomainLoading ? 'loading...' : restrictionReason
                        }
                    >
                        Add domain
                    </Button>
                </div>
            </div>
            <AddDomainModal />
            {!isSSOSettingsRedesignEnabled && (
                <>
                    <ConfigureSAMLModal />
                    <ConfigureSCIMModal />
                    {showXAAControls && <ConfigureIdJagModal />}
                    <ScimLogsModal />
                </>
            )}
            <VerifyDomainModal />
            <RemoveDomainModal />
        </PayGateMini>
    )
}
