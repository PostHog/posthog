import { useValues } from 'kea'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { TodaySessionBadges } from './TodaySessionBadges'
import { todaySessionDot } from './todaySessionDot'
import { TodaySessionMenu } from './TodaySessionMenu'
import { TodaySessionSurface, todaySessionMenuLogic } from './todaySessionMenuLogic'
import { TodaySessionRenameInput } from './TodaySessionRenameInput'
import { TodaySessionStatusDot } from './TodaySessionStatusDot'
import { todaySpacesLogic } from './todaySpacesLogic'
import { TodaySpacesRow } from './TodaySpacesRow'
import { TodayWorkItem, activeCloudRunId, analysisRunId, canHandOff } from './todayWorkItems'

interface TodaySessionRowProps {
    item: TodayWorkItem
    pinned: boolean
    /** False under the Pinned heading, which already says it for every row. */
    showPinBadge: boolean
    dataAttr: string
    surface: TodaySessionSurface
    unread: boolean
}

export function TodaySessionRow({
    item,
    pinned,
    showPinBadge,
    dataAttr,
    surface,
    unread,
}: TodaySessionRowProps): JSX.Element {
    const { renaming } = useValues(todaySessionMenuLogic)
    const { location, searchParams } = useValues(router)
    const { user } = useValues(userLogic)
    const { pullRequestStates } = useValues(todaySpacesLogic)

    const [pullRequest] = item.pullRequests
    const pinBadge = pinned && showPinBadge
    const badgeCount = (pullRequest ? 1 : 0) + (pinBadge ? 1 : 0)

    if (renaming?.sessionId === item.id && renaming.surface === surface) {
        return <TodaySessionRenameInput sessionId={item.id} title={item.title} />
    }
    return (
        <TodaySpacesRow
            label={item.title || 'Untitled session'}
            // Unread shows only as a solid status dot; the title keeps its resting weight, like desktop.
            icon={<TodaySessionStatusDot dot={todaySessionDot(item, unread)} />}
            to={urls.aiTask(item.id)}
            active={location.pathname.endsWith('/ai') && searchParams.task === item.id}
            dataAttr={dataAttr}
            badge={
                badgeCount > 0 ? (
                    <TodaySessionBadges
                        pullRequest={pullRequest ?? null}
                        pullRequestState={pullRequest ? pullRequestStates[pullRequest.url] : null}
                        pinned={pinBadge}
                    />
                ) : null
            }
            badgeCount={badgeCount === 2 ? 2 : 1}
            ticker
            action={
                <TodaySessionMenu
                    sessionId={item.id}
                    title={item.title}
                    pinned={pinned}
                    spaceId={item.channel}
                    surface={surface}
                    canHandOff={canHandOff(item, user?.id)}
                    analysisRunId={analysisRunId(item)}
                    activeRunId={activeCloudRunId(item)}
                />
            }
        />
    )
}
