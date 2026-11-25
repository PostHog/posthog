import { decode } from 'he'
import { useActions, useValues } from 'kea'

import {
    Badge,
    Button,
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
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { urls } from 'scenes/urls'

import { oauthAppsLogic } from './oauthAppsLogic'
import { QuillCopyableCode } from './QuillCopyableCode'
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
                    <Item key={app.id} variant="outline" size="sm">
                        <ItemContent className="flex-row flex-wrap items-center gap-2">
                            <Button
                                variant="link-foreground"
                                size="sm"
                                nativeButton={false}
                                render={<LinkPrimitive to={urls.oauthApplication(app.id)} />}
                                data-attr="oauth-app-open"
                            >
                                {name}
                            </Button>
                            {app.is_verified && <Badge variant="success">Verified</Badge>}
                            {app.provisioning_status !== 'not_a_partner' && (
                                <QuillProvisioningStatusBadge status={app.provisioning_status} />
                            )}
                        </ItemContent>
                        <ItemActions className="flex-wrap">
                            <QuillCopyableCode
                                value={app.client_id ?? ''}
                                label="Copy client ID"
                                onCopy={() => void copyToClipboard(app.client_id ?? '', 'client ID')}
                            />
                            <Text size="xs" variant="muted" render={<span />}>
                                {`Connected ${humanFriendlyDetailedTime(app.created)}`}
                            </Text>
                        </ItemActions>
                    </Item>
                )
            })}
        </div>
    )
}
