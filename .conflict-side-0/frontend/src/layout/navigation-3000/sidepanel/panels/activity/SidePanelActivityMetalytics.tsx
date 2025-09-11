import { useValues } from 'kea'

import { Spinner, Tooltip } from '@posthog/lemon-ui'

import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import { metalyticsLogic } from 'lib/components/Metalytics/metalyticsLogic'
import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture/ProfileBubbles'

export function SidePanelActivityMetalytics(): JSX.Element {
    const { scope, instanceId, viewCount, recentUserMembers, viewCountLoading, recentUsersLoading } =
        useValues(metalyticsLogic)

    if (!instanceId) {
        return (
            <p className="border-dashed ">
                You can see internal analytics of how your Organization members are using PostHog for things such as
                Dashboards, Insights, Playlists etc. Open an app to see the viewership data here.
            </p>
        )
    }

    const humanizedScope = `this ${scope ? humanizeScope(scope, true) : 'app'}`

    return (
        <div className="deprecated-space-y-4 ">
            <p>
                You are viewing "meta" analytics of how your organization members are interacting with{' '}
                <b>{humanizedScope}</b>.
            </p>
            <div className="flex flex-wrap gap-4">
                <Tooltip
                    title={`The total number of times ${humanizedScope} has been viewed by members of your organization.`}
                    placement="top"
                >
                    <div className="flex-1 p-4 border rounded bg-surface-primary min-w-40">
                        <div className="text-sm text-secondary">Views</div>
                        <div className="text-2xl font-semibold">
                            {viewCountLoading ? <Spinner /> : (viewCount?.views ?? 0)}
                        </div>
                    </div>
                </Tooltip>

                <Tooltip
                    title={`The total number of unique organization members who have viewed ${humanizedScope}.`}
                    placement="top"
                >
                    <div className="flex-1 p-4 border rounded bg-surface-primary min-w-40">
                        <div className="text-sm text-secondary">Viewers</div>
                        <div className="text-2xl font-semibold">
                            {viewCountLoading ? <Spinner /> : (viewCount?.users ?? 0)}
                        </div>
                    </div>
                </Tooltip>

                <Tooltip title={`The most recent 30 users who have viewed ${humanizedScope}.`} placement="top">
                    <div className="flex-1 p-4 border rounded bg-surface-primary min-w-40">
                        <div className="text-sm text-secondary">Recent viewers (30 days)</div>
                        {recentUsersLoading ? (
                            <Spinner />
                        ) : recentUserMembers.length > 0 ? (
                            <ProfileBubbles
                                className="mt-2"
                                people={recentUserMembers.map((member) => ({
                                    email: member.user.email,
                                    name: member.user.first_name,
                                    title: member.user.email,
                                }))}
                                limit={3}
                            />
                        ) : (
                            <div className="text-sm mt-2">No recent viewers</div>
                        )}
                    </div>
                </Tooltip>
            </div>
        </div>
    )
}
