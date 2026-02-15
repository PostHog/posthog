import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'

export function DiscussionMentionNotifications(): JSX.Element {
    return (
        <div>
            <p className="flex items-center gap-1">
                Get notified when someone mentions you in a discussion.
                <Tooltip
                    title={
                        <>
                            Configure destination integrations (e.g., Slack, Discord, Microsoft Teams) to receive
                            notifications when you are mentioned in discussions on replays, notebooks, insights, and
                            other items.
                        </>
                    }
                >
                    <IconInfo className="text-lg" />
                </Tooltip>
            </p>

            <LinkedHogFunctions
                type="internal_destination"
                subTemplateIds={['discussion-mention']}
                emptyText="No notifications configured"
            />
        </div>
    )
}
