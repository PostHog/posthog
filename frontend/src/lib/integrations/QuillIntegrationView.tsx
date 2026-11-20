import { IconTrash } from '@posthog/icons'
import {
    Button,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { QuillUserActivityIndicator } from 'lib/components/UserActivityIndicator/QuillUserActivityIndicator'
import { dayjs } from 'lib/dayjs'
import { IntegrationScopesWarning } from 'lib/integrations/IntegrationScopesWarning'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { IntegrationType } from '~/types'

import { DARK_MODE_INVERT_ICON_KINDS, IntegrationConnectSurface, getIntegrationNameFromKind } from './utils'

export function QuillIntegrationView({
    integration,
    suffix,
    actions,
    schema,
    hideWebhookReconnect,
    restrictedReason,
    errors,
    installationUnavailable,
    refreshedAtTimestamp,
    githubRepoSummary,
    onDisconnect,
    reconnectUrl,
    onReconnectClick,
}: {
    integration: IntegrationType
    suffix?: JSX.Element
    actions?: JSX.Element | null
    schema?: { requiredScopes?: string }
    hideWebhookReconnect?: boolean
    restrictedReason: string | null
    errors: string[]
    installationUnavailable: boolean
    refreshedAtTimestamp: number | null
    githubRepoSummary: JSX.Element | null
    onDisconnect: () => void
    reconnectUrl: string
    onReconnectClick: (surface: IntegrationConnectSurface) => void
}): JSX.Element {
    const integrationName = getIntegrationNameFromKind(integration.kind)

    const reconnectButton = (surface: IntegrationConnectSurface): JSX.Element => (
        <Button
            variant="outline"
            nativeButton={false}
            render={<LinkPrimitive to={reconnectUrl} disableClientSideRouting />}
            onClick={() => onReconnectClick(surface)}
            disabledReason={restrictedReason}
        >
            Reconnect
        </Button>
    )

    return (
        <div className="flex flex-col rounded-md border border-border">
            <div className="flex flex-wrap items-center justify-between gap-2 p-2">
                <div className="flex min-w-0 items-center gap-4">
                    <img
                        src={integration.icon_url}
                        alt={`Integration for ${integrationName}`}
                        title={integrationName}
                        className={cn(
                            'size-10 shrink-0 rounded-sm',
                            DARK_MODE_INVERT_ICON_KINDS.has(integration.kind) && 'dark:invert'
                        )}
                    />
                    <div className="flex min-w-0 flex-col">
                        <Text size="xs" render={<span />}>
                            {installationUnavailable ? (
                                <span>No longer connected</span>
                            ) : refreshedAtTimestamp ? (
                                <Tooltip>
                                    <TooltipTrigger render={<strong className="cursor-help underline" />}>
                                        Connected
                                    </TooltipTrigger>
                                    <TooltipContent>
                                        <span className="flex items-baseline gap-1">
                                            <span>Last refreshed</span>
                                            <TZLabel time={dayjs.unix(refreshedAtTimestamp)} />
                                        </span>
                                    </TooltipContent>
                                </Tooltip>
                            ) : (
                                <span>Connected</span>
                            )}{' '}
                            to <strong>{integration.display_name}</strong>
                        </Text>
                        {integration.created_by ? (
                            <QuillUserActivityIndicator
                                at={integration.created_at}
                                by={integration.created_by}
                                prefix="Created"
                            />
                        ) : null}
                        {githubRepoSummary}
                    </div>
                </div>

                {suffix || (
                    <div className="flex flex-wrap gap-2">
                        {actions}
                        <Button variant="destructive-outline" onClick={onDisconnect} disabledReason={restrictedReason}>
                            <IconTrash />
                            Disconnect
                        </Button>
                    </div>
                )}
            </div>

            {installationUnavailable ? (
                <div className="p-2">
                    <Item tone="destructive" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                The PostHog app was removed from GitHub. Remove this connection or reinstall the app.
                            </ItemDescription>
                        </ItemContent>
                        <ItemActions className="flex-wrap">
                            <Button
                                variant="destructive-outline"
                                onClick={onDisconnect}
                                disabledReason={restrictedReason}
                            >
                                Remove
                            </Button>
                            {reconnectButton('unavailable_banner_reconnect')}
                        </ItemActions>
                    </Item>
                </div>
            ) : errors.length > 0 ? (
                <div className="p-2">
                    <Item tone="destructive" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                {errors[0] === 'TOKEN_REFRESH_FAILED'
                                    ? 'Authentication token could not be refreshed. You can reconnect this account or disconnect it and connect a different one.'
                                    : `There was an error with this integration: ${errors[0]}`}
                            </ItemDescription>
                        </ItemContent>
                        <ItemActions>{reconnectButton('error_banner_reconnect')}</ItemActions>
                    </Item>
                </div>
            ) : integration.needs_webhook_reconnect && !hideWebhookReconnect ? (
                <div className="p-2">
                    <Item tone="info" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                Error tracking issues can now sync their status with linked Linear tickets. To turn this
                                on, switch to <strong>{integration.display_name}</strong> in Linear and reconnect.
                            </ItemDescription>
                        </ItemContent>
                        <ItemActions>{reconnectButton('webhook_banner_reconnect')}</ItemActions>
                    </Item>
                </div>
            ) : (
                <IntegrationScopesWarning integration={integration} schema={schema} />
            )}
        </div>
    )
}
