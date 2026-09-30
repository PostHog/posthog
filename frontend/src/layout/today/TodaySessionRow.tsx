import { useValues } from 'kea'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { TaskPullRequestChip } from 'products/tasks/frontend/spaces/TaskPullRequestChip'

import { TodaySessionMenu } from './TodaySessionMenu'
import { TodaySessionSurface, todaySessionMenuLogic } from './todaySessionMenuLogic'
import { TodaySessionRenameInput } from './TodaySessionRenameInput'
import { TodaySessionStatusIcon } from './TodaySessionStatusIcon'
import { TodaySpacesRow } from './TodaySpacesRow'
import { TodayWorkItem, activeCloudRunId, analysisRunId, canHandOff, runStatusLabel } from './todayWorkItems'

interface TodaySessionRowProps {
    item: TodayWorkItem
    pinned: boolean
    dataAttr: string
    surface: TodaySessionSurface
}

export function TodaySessionRow({ item, pinned, dataAttr, surface }: TodaySessionRowProps): JSX.Element {
    const { renaming } = useValues(todaySessionMenuLogic)
    const { location, searchParams } = useValues(router)
    const { user } = useValues(userLogic)

    const [pullRequest] = item.pullRequests

    if (renaming?.sessionId === item.id && renaming.surface === surface) {
        return <TodaySessionRenameInput sessionId={item.id} title={item.title} />
    }
    return (
        <TodaySpacesRow
            label={item.title || 'Untitled session'}
            icon={<TodaySessionStatusIcon item={item} pinned={pinned} />}
            to={urls.aiTask(item.id)}
            active={location.pathname.endsWith('/ai') && searchParams.task === item.id}
            dataAttr={dataAttr}
            preview={{ kind: 'session', item }}
            description={[runStatusLabel(item.status), item.lastMessage].filter(Boolean).join('. ')}
            badge={
                pullRequest ? (
                    <TaskPullRequestChip
                        pullRequest={pullRequest}
                        label={`#${pullRequest.number}`}
                        dataAttr="today-pr-chip-sidebar"
                    />
                ) : null
            }
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
