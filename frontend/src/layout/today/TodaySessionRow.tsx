import { useValues } from 'kea'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { TodaySessionMenu } from './TodaySessionMenu'
import { TodaySessionSurface, todaySessionMenuLogic } from './todaySessionMenuLogic'
import { TodaySessionRenameInput } from './TodaySessionRenameInput'
import { TodaySessionStatusIcon } from './TodaySessionStatusIcon'
import { TodaySpacesRow } from './TodaySpacesRow'
import { TodayWorkItem } from './todayWorkItems'

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
        return (
            <div data-not-quill>
                <TodaySessionRenameInput sessionId={item.id} title={item.title} />
            </div>
        )
    }
    return (
        <TodaySpacesRow
            label={item.title || 'Untitled session'}
            icon={<TodaySessionStatusIcon item={item} pinned={pinned} />}
            to={urls.aiTask(item.id)}
            active={location.pathname.endsWith('/ai') && searchParams.task === item.id}
            dataAttr={dataAttr}
            action={<TodaySessionMenu sessionId={item.id} pinned={pinned} spaceId={item.channel} surface={surface} />}
        />
    )
}
