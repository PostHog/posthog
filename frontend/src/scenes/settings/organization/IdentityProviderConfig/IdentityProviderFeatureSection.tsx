import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconCircleDashed, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ConfigScopeEnumApi } from '~/generated/core/api.schemas'

import { ScimLogsModal } from '../VerifiedDomains/ScimLogsModal'
import { verifiedDomainsLogic } from '../VerifiedDomains/verifiedDomainsLogic'
import { identityProviderConfigsLogic } from './identityProviderConfigsLogic'
import {
    IDENTITY_PROVIDER_FEATURES,
    getIdentityProviderConfigForScope,
    getIdentityProviderConfigStatus,
    getIdentityProviderConfigStatusDescription,
} from './identityProviderConfigUtils'

const STATUS_DISPLAY = {
    configured: { label: 'Configured', icon: <IconCheckCircle className="size-6 text-success" /> },
    partially_configured: { label: 'Partially configured', icon: <IconWarning className="size-6 text-warning" /> },
    not_configured: { label: 'Not configured', icon: <IconCircleDashed className="size-6 text-muted" /> },
}

export function IdentityProviderFeatureSection({ configScope }: { configScope: ConfigScopeEnumApi }): JSX.Element {
    const { identityProviderConfigs, identityProviderConfigsLoading, identityProviderConfigsLoadFailed } =
        useValues(identityProviderConfigsLogic)
    const { loadIdentityProviderConfigs } = useActions(identityProviderConfigsLogic)
    const { scimLogsLoading, verifiedDomains } = useValues(verifiedDomainsLogic)
    const { setScimConfigLogsModalId } = useActions(verifiedDomainsLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const feature = IDENTITY_PROVIDER_FEATURES[configScope]
    const config = identityProviderConfigs
        ? getIdentityProviderConfigForScope(identityProviderConfigs, configScope)
        : undefined
    const configStatus = getIdentityProviderConfigStatus(config, configScope)
    const status = STATUS_DISPLAY[configStatus]
    const statusDescription = getIdentityProviderConfigStatusDescription(
        config,
        configScope,
        configStatus,
        verifiedDomains
    )
    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })
    const unavailableReason = hasAvailableFeature(feature.availableFeature)
        ? undefined
        : `Upgrade your plan to configure ${feature.name}`

    if (identityProviderConfigs === null && !identityProviderConfigsLoadFailed) {
        return <LemonSkeleton className="h-16 w-full" />
    }

    if (identityProviderConfigsLoadFailed) {
        return (
            <LemonBanner
                type="error"
                action={{
                    children: 'Try again',
                    onClick: loadIdentityProviderConfigs,
                    loading: identityProviderConfigsLoading,
                }}
            >
                Couldn't load identity provider configurations.
            </LemonBanner>
        )
    }

    return (
        <>
            <LemonCard hoverEffect={false} className="flex flex-wrap items-center justify-between gap-4 p-4">
                <div className="flex min-w-0 items-start gap-2">
                    <span className="mt-0.5 shrink-0">{status.icon}</span>
                    <div className="min-w-0">
                        <div className="text-base font-medium">{status.label}</div>
                        <p className="mb-0 text-sm text-tertiary">
                            {statusDescription.text}
                            {statusDescription.emphasizedText && <strong>{statusDescription.emphasizedText}</strong>}
                            {statusDescription.trailingText}
                        </p>
                    </div>
                </div>
                <div className="flex flex-wrap gap-2">
                    {configScope === ConfigScopeEnumApi.Scim && (
                        <LemonButton
                            type="secondary"
                            onClick={() => config && setScimConfigLogsModalId(config.id)}
                            loading={scimLogsLoading}
                            disabledReason={
                                restrictionReason ||
                                unavailableReason ||
                                (!config ? 'Configure SCIM to view request logs' : undefined)
                            }
                            data-attr="view-scim-logs"
                        >
                            View SCIM logs
                        </LemonButton>
                    )}
                    <LemonButton
                        type="secondary"
                        to={urls.identityProviderConfig(configScope, config?.id ?? 'new')}
                        disabledReason={restrictionReason || unavailableReason}
                        data-attr={`configure-${configScope}-identity-provider`}
                    >
                        Configure
                    </LemonButton>
                </div>
            </LemonCard>
            {configScope === ConfigScopeEnumApi.Scim && <ScimLogsModal emptyStateScope="configuration" />}
        </>
    )
}
