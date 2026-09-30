import { useValues } from 'kea'
import { router } from 'kea-router'

import { Dot } from '@posthog/quill'

import { urls } from 'scenes/urls'

import { TodayPaneRow } from './TodayPaneRow'
import { TodaySessionMenu } from './TodaySessionMenu'
import { todaySessionMenuLogic } from './todaySessionMenuLogic'
import { TodaySessionRenameInput } from './TodaySessionRenameInput'
import { TodayWorkItem, shortTimeAgo, statusDotVariant } from './todayWorkItems'

interface TodaySessionRowProps {
    item: TodayWorkItem
    pinned: boolean
    dataAttr: string
}

export function TodaySessionRow({ item, pinned, dataAttr }: TodaySessionRowProps): JSX.Element {
    const { renamingSessionId } = useValues(todaySessionMenuLogic)
    const { location, searchParams } = useValues(router)

    if (renamingSessionId === item.id) {
        return <TodaySessionRenameInput sessionId={item.id} title={item.title} />
    }
    return (
        <TodayPaneRow
            label={item.title || 'Untitled session'}
            icon={<Dot variant={statusDotVariant(item.status)} />}
            meta={shortTimeAgo(item.timestamp)}
            to={urls.aiTask(item.id)}
            active={location.pathname.endsWith('/ai') && searchParams.task === item.id}
            dataAttr={dataAttr}
            action={<TodaySessionMenu sessionId={item.id} pinned={pinned} spaceId={item.channel} />}
        />
    )
}
