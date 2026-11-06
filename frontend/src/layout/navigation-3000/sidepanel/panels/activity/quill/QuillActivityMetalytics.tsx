import { useValues } from 'kea'

import { Item, ItemContent, ItemDescription, ItemTitle, Skeleton, Text } from '@posthog/quill'

import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import { metalyticsLogic } from 'lib/components/Metalytics/metalyticsLogic'

import { QuillPeopleAvatars } from '../../../components/QuillPeopleAvatars'

function Stat({
    label,
    description,
    loading,
    children,
}: {
    label: string
    description: string
    loading: boolean
    children: React.ReactNode
}): JSX.Element {
    return (
        <Item variant="outline" size="sm">
            <ItemContent>
                <ItemDescription>{label}</ItemDescription>
                <ItemTitle className="text-base">{loading ? <Skeleton className="h-6 w-12" /> : children}</ItemTitle>
                <Text size="xs" variant="muted">
                    {description}
                </Text>
            </ItemContent>
        </Item>
    )
}

export function QuillActivityMetalytics(): JSX.Element {
    const { scope, instanceId, viewCount, recentUserMembers, viewCountLoading, recentUsersLoading } =
        useValues(metalyticsLogic)

    if (!instanceId) {
        return (
            <Text size="xs" variant="muted">
                See how members of your organization use things like dashboards, insights, and playlists. Open one to
                see who views it.
            </Text>
        )
    }

    const humanizedScope = `this ${scope ? humanizeScope(scope, true).toLowerCase() : 'app'}`

    return (
        <div className="flex flex-col gap-2">
            <Text size="xs" variant="muted">
                How members of your organization interact with {humanizedScope}.
            </Text>
            <Stat
                label="Views"
                description={`Times members of your organization viewed ${humanizedScope}.`}
                loading={viewCountLoading}
            >
                {viewCount?.views ?? 0}
            </Stat>
            <Stat
                label="Viewers"
                description={`Members of your organization who viewed ${humanizedScope}.`}
                loading={viewCountLoading}
            >
                {viewCount?.users ?? 0}
            </Stat>
            <Stat
                label="Recent viewers (30 days)"
                description={`The latest 30 members who viewed ${humanizedScope}.`}
                loading={recentUsersLoading}
            >
                {recentUserMembers.length > 0 ? (
                    <QuillPeopleAvatars
                        people={recentUserMembers.map((member) => ({
                            email: member.user.email,
                            name: member.user.first_name,
                        }))}
                    />
                ) : (
                    <Text size="xs" variant="muted" render={<span className="m-0" />}>
                        No recent viewers
                    </Text>
                )}
            </Stat>
        </div>
    )
}
