import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconCircleDashed, IconWarning } from '@posthog/icons'
import {
    Badge,
    Button,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemTitle,
    Skeleton,
} from '@posthog/quill'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { ConfigScopeEnumApi, IdentityProviderConfigApi } from '~/generated/core/api.schemas'

import { ScimLogsModal } from '../VerifiedDomains/ScimLogsModal'
import { verifiedDomainsLogic } from '../VerifiedDomains/verifiedDomainsLogic'
import { identityProviderConfigsLogic } from './identityProviderConfigsLogic'
import {
    IDENTITY_PROVIDER_FEATURES,
    getIdentityProviderConfigStatus,
    getIdentityProviderConfigStatusDescription,
} from './identityProviderConfigUtils'

const STATUS_DISPLAY = {
    configured: { label: 'Configured', icon: <IconCheckCircle className="text-success-foreground" /> },
    partially_configured: {
        label: 'Partially configured',
        icon: <IconWarning className="text-warning-foreground" />,
    },
    not_configured: { label: 'Not configured', icon: <IconCircleDashed className="text-muted-foreground" /> },
}

export function QuillIdentityProviderFeatureSection({
    configScope,
    configs,
    configsToDisplay,
    restrictionReason,
    configureButtonLabel,
}: {
    configScope: ConfigScopeEnumApi
    configs: IdentityProviderConfigApi[]
    configsToDisplay: (IdentityProviderConfigApi | undefined)[]
    restrictionReason: string | null
    configureButtonLabel: (config: IdentityProviderConfigApi | undefined) => string
}): JSX.Element {
    const { identityProviderConfigs, identityProviderConfigsLoading, identityProviderConfigsLoadFailed } =
        useValues(identityProviderConfigsLogic)
    const { loadIdentityProviderConfigs } = useActions(identityProviderConfigsLogic)
    const { scimLogsLoading, verifiedDomains } = useValues(verifiedDomainsLogic)
    const { setScimConfigLogsModalId } = useActions(verifiedDomainsLogic)

    const feature = IDENTITY_PROVIDER_FEATURES[configScope]

    let content: JSX.Element
    if (identityProviderConfigs === null && !identityProviderConfigsLoadFailed) {
        content = <Skeleton className="h-16 w-full" />
    } else if (identityProviderConfigsLoadFailed) {
        content = (
            <Item tone="destructive" size="sm">
                <ItemContent>
                    <ItemDescription>Couldn't load identity provider configurations.</ItemDescription>
                </ItemContent>
                <ItemActions>
                    <Button
                        variant="outline"
                        onClick={loadIdentityProviderConfigs}
                        loading={identityProviderConfigsLoading}
                    >
                        Try again
                    </Button>
                </ItemActions>
            </Item>
        )
    } else {
        content = (
            <div className="flex flex-col gap-2">
                {configsToDisplay.map((config) => {
                    const configStatus = getIdentityProviderConfigStatus(config, configScope)
                    const status = STATUS_DISPLAY[configStatus]
                    const statusDescription = getIdentityProviderConfigStatusDescription(
                        config,
                        configScope,
                        configStatus,
                        verifiedDomains
                    )

                    return (
                        <Item key={config?.id ?? 'not-configured'} variant="outline" className="flex-wrap">
                            <ItemMedia variant="icon">{status.icon}</ItemMedia>
                            <ItemContent className="min-w-0">
                                <ItemTitle className="flex-wrap">
                                    <span>{status.label}</span>
                                    {config?.name && (
                                        <span className="text-muted-foreground">{`- ${config.name}`}</span>
                                    )}
                                    {config?.id_jag_registered_by_application_name && (
                                        <Badge variant="warning">
                                            {`Set up from ${config.id_jag_registered_by_application_name}`}
                                        </Badge>
                                    )}
                                </ItemTitle>
                                <ItemDescription>
                                    {statusDescription.text}
                                    {statusDescription.emphasizedText && (
                                        <strong>{statusDescription.emphasizedText}</strong>
                                    )}
                                    {statusDescription.trailingText}
                                </ItemDescription>
                            </ItemContent>
                            <ItemActions className="flex-wrap">
                                {configScope === ConfigScopeEnumApi.Scim && (
                                    <Button
                                        variant="outline"
                                        onClick={() => config && setScimConfigLogsModalId(config.id)}
                                        loading={scimLogsLoading}
                                        disabledReason={
                                            restrictionReason ||
                                            (!config ? 'Configure SCIM to view request logs' : undefined)
                                        }
                                        data-attr={`view-scim-logs-${config?.id ?? 'none'}`}
                                    >
                                        View SCIM logs
                                    </Button>
                                )}
                                <Button
                                    variant="outline"
                                    nativeButton={false}
                                    render={
                                        <LinkPrimitive
                                            to={urls.identityProviderConfig(configScope, config?.id ?? 'new')}
                                        />
                                    }
                                    disabledReason={restrictionReason}
                                    data-attr={`configure-${configScope}-identity-provider`}
                                >
                                    {configureButtonLabel(config)}
                                </Button>
                            </ItemActions>
                        </Item>
                    )
                })}
                {configs.length > 0 && (
                    <div className="flex">
                        <Button
                            nativeButton={false}
                            render={<LinkPrimitive to={urls.identityProviderConfig(configScope, 'new')} />}
                            tooltip="You probably don't need multiple configurations. Only create a new configuration if you use multiple IdPs or apps within your IdP for SSO."
                            data-attr={`new-${configScope}-identity-provider-from-settings`}
                        >
                            {`Add a new ${feature.name} configuration`}
                        </Button>
                    </div>
                )}
                {configScope === ConfigScopeEnumApi.Scim && <ScimLogsModal emptyStateScope="configuration" />}
            </div>
        )
    }

    return (
        <PayGateMini
            feature={feature.availableFeature}
            featureDetail={`${configScope}-settings-section`}
            loadingSkeleton={<Skeleton className="h-16 w-full" />}
        >
            {content}
        </PayGateMini>
    )
}
