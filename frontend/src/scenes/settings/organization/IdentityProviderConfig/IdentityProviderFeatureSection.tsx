import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCard, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ConfigScopeEnumApi } from '~/generated/core/api.schemas'

import { identityProviderConfigsLogic } from './identityProviderConfigsLogic'
import {
    IDENTITY_PROVIDER_FEATURES,
    getIdentityProviderConfigForScope,
    getIdentityProviderConfigStatus,
} from './identityProviderConfigUtils'

const STATUS_DISPLAY = {
    configured: { label: 'Configured', type: 'success' as const },
    partially_configured: { label: 'Partially configured', type: 'warning' as const },
    not_configured: { label: 'Not configured', type: 'muted' as const },
}

export function IdentityProviderFeatureSection({ configScope }: { configScope: ConfigScopeEnumApi }): JSX.Element {
    const { identityProviderConfigs, identityProviderConfigsLoading, identityProviderConfigsLoadFailed } =
        useValues(identityProviderConfigsLogic)
    const { loadIdentityProviderConfigs } = useActions(identityProviderConfigsLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const feature = IDENTITY_PROVIDER_FEATURES[configScope]
    const config = identityProviderConfigs
        ? getIdentityProviderConfigForScope(identityProviderConfigs, configScope)
        : undefined
    const status = STATUS_DISPLAY[getIdentityProviderConfigStatus(config, configScope)]
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
        <LemonCard hoverEffect={false} className="flex flex-wrap items-center justify-between gap-3 p-4">
            <div className="flex items-center gap-2">
                <span className="font-medium">Status</span>
                <LemonTag type={status.type}>{status.label}</LemonTag>
            </div>
            <LemonButton
                type="secondary"
                to={urls.identityProviderConfig(configScope, config?.id ?? 'new')}
                disabledReason={restrictionReason || unavailableReason}
                data-attr={`configure-${configScope}-identity-provider`}
            >
                Configure
            </LemonButton>
        </LemonCard>
    )
}
