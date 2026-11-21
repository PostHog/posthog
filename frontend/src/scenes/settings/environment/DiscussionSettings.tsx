import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import { Text } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { urls } from 'scenes/urls'

const MENTION_DESTINATIONS_HELP =
    'Configure destination integrations (e.g., Slack, Discord, Microsoft Teams) to receive notifications when you are mentioned in discussions on replays, notebooks, insights, and other items.'

export function DiscussionMentionNotifications(): JSX.Element | null {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (restrictedReason) {
        return null
    }

    const linkedHogFunctions = (
        <LinkedHogFunctions
            type="internal_destination"
            subTemplateIds={['discussion-mention']}
            emptyText="No notifications configured"
            queryParams={{
                returnTo: urls.settings('environment-discussions', 'discussion-mention-integrations'),
            }}
        />
    )

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <Text size="xs" render={<p className="m-0" />}>
                    Get notified when someone mentions you in a discussion.
                </Text>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    {MENTION_DESTINATIONS_HELP}
                </Text>
                {linkedHogFunctions}
            </div>
        )
    }

    return (
        <div>
            <p className="flex items-center gap-1">
                Get notified when someone mentions you in a discussion.
                <Tooltip title={MENTION_DESTINATIONS_HELP}>
                    <IconInfo className="text-lg" />
                </Tooltip>
            </p>

            {linkedHogFunctions}
        </div>
    )
}
