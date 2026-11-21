import { useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { Button, Item, ItemActions, ItemContent, ItemDescription } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { teamLogic } from 'scenes/teamLogic'

import { getIntegrationsAuthorizeRetrieveUrl } from 'products/integrations/frontend/generated/api'

export function QuillSlackIntegrationInactiveBanner({ message }: { message: string }): JSX.Element {
    // Reconnecting overwrites the existing integration, which the API reserves for project admins
    // (`has_team_management_access`). Without this the banner would send a member through OAuth
    // only to have the write rejected at the end.
    const reconnectRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })
    const { currentTeamId } = useValues(teamLogic)

    return (
        <Item tone="warning" size="sm" className="flex-wrap">
            <ItemContent>
                <ItemDescription>
                    {message}
                    {reconnectRestrictionReason ? ' Ask a project admin to reconnect it.' : ''}
                </ItemDescription>
            </ItemContent>
            {reconnectRestrictionReason ? null : (
                <ItemActions>
                    <Button
                        variant="outline"
                        nativeButton={false}
                        render={
                            <LinkPrimitive
                                to={
                                    combineUrl(getIntegrationsAuthorizeRetrieveUrl(String(currentTeamId)), {
                                        kind: 'slack',
                                        next: window.location.pathname + '?target_type=slack',
                                    }).url
                                }
                                disableClientSideRouting
                            />
                        }
                    >
                        Reconnect Slack
                    </Button>
                </ItemActions>
            )}
        </Item>
    )
}
