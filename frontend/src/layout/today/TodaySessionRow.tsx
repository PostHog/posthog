import { useValues } from 'kea'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { TodayPaneRow } from './TodayPaneRow'
import { TodaySessionMenu } from './TodaySessionMenu'
import { TodaySessionSurface, todaySessionMenuLogic } from './todaySessionMenuLogic'
import { TodaySessionRenameInput } from './TodaySessionRenameInput'
import { TodayWorkItem, shortTimeAgo } from './todayWorkItems'

interface TodaySessionRowProps {
    item: TodayWorkItem
    pinned: boolean
    dataAttr: string
    surface: TodaySessionSurface
}

export function TodaySessionRow({ item, pinned, dataAttr, surface }: TodaySessionRowProps): JSX.Element {
    const { renaming } = useValues(todaySessionMenuLogic)
    const { location, searchParams } = useValues(router)

    if (renaming?.sessionId === item.id && renaming.surface === surface) {
        return <TodaySessionRenameInput sessionId={item.id} title={item.title} />
    }
    return (
        <TodayPaneRow
            label={item.title || 'Untitled session'}
            icon={<span className="TodayPane__dot" data-kind={item.kind} data-status={item.status ?? undefined} />}
            meta={shortTimeAgo(item.timestamp)}
            to={urls.aiTask(item.id)}
            active={location.pathname.endsWith('/ai') && searchParams.task === item.id}
            dataAttr={dataAttr}
            action={<TodaySessionMenu sessionId={item.id} pinned={pinned} spaceId={item.channel} surface={surface} />}
        />
    )
}
