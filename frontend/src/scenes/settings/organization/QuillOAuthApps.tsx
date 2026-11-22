import { decode } from 'he'
import { useActions, useValues } from 'kea'

import {
    Badge,
    Button,
    Collapsible,
    CollapsibleContent,
    CollapsibleHeader,
    CollapsibleTrigger,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Skeleton,
    Text,
} from '@posthog/quill'

import { IconKey } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { oauthAppsLogic } from './oauthAppsLogic'
import { QuillCopyableCode } from './QuillCopyableCode'
import { QuillOAuthAppDetails } from './QuillOAuthAppDetails'
import { QuillProvisioningStatusBadge } from './QuillProvisioningStatusBadge'

export function QuillOAuthApps(): JSX.Element {
    const { oauthApps, oauthAppsLoading, oauthAppsLoadFailed } = useValues(oauthAppsLogic)
    const { loadOAuthApps } = useActions(oauthAppsLogic)

    if (oauthAppsLoadFailed && !oauthAppsLoading) {
        return (
            <Item tone="destructive" size="sm">
                <ItemContent>
                    <ItemDescription>
                        Couldn't load your OAuth applications. Try again, and if it keeps happening contact support.
                    </ItemDescription>
                </ItemContent>
                <ItemActions>
                    <Button variant="outline" onClick={loadOAuthApps} data-attr="oauth-apps-retry">
                        Try again
                    </Button>
                </ItemActions>
            </Item>
        )
    }

    if (oauthApps === null || (oauthAppsLoading && oauthApps.length === 0)) {
        return (
            <div className="flex flex-col gap-2">
                <Skeleton className="h-12" />
                <Skeleton className="h-12" />
            </div>
        )
    }

    if (oauthApps.length === 0) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconKey />
                    </EmptyMedia>
                    <EmptyTitle>No connected applications</EmptyTitle>
                    <EmptyDescription>
                        Applications will appear here when third-party tools connect to your organization.
                    </EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            {oauthApps.map((app) => {
                const name = decode(app.name ?? '')

                return (
                    <Collapsible key={app.id} className="rounded-md border border-border p-2">
                        <CollapsibleHeader className="flex-wrap">
                            <CollapsibleTrigger iconOnly>{`Show details for ${name}`}</CollapsibleTrigger>
                            <Text size="xs" weight="semibold" render={<span className="min-w-0 truncate" />}>
                                {name}
                            </Text>
                            {app.is_verified && <Badge variant="success">Verified</Badge>}
                            {app.provisioning_status !== 'not_a_partner' && (
                                <QuillProvisioningStatusBadge status={app.provisioning_status} />
                            )}
                            <span className="ms-auto flex flex-wrap items-center gap-3">
                                <QuillCopyableCode
                                    value={app.client_id ?? ''}
                                    label="Copy client ID"
                                    onCopy={() => void copyToClipboard(app.client_id ?? '', 'client ID')}
                                />
                                <Text size="xs" variant="muted" render={<span />}>
                                    {`Connected ${humanFriendlyDetailedTime(app.created)}`}
                                </Text>
                            </span>
                        </CollapsibleHeader>
                        <CollapsibleContent className="pt-2">
                            <QuillOAuthAppDetails app={app} />
                        </CollapsibleContent>
                    </Collapsible>
                )
            })}
        </div>
    )
}
