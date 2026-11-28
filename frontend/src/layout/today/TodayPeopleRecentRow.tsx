import { IconBuilding, IconPeople, IconPerson, IconSupport } from '@posthog/icons'

import { TodayPeopleRecent, TodayPeopleRecentType } from './todayPeople'
import { TodayRecentRow } from './TodayRecentRow'
import { todayRecordType } from './todayRecordTypes'

const RECENT_TYPE_ICONS: Record<TodayPeopleRecentType, JSX.Element> = {
    person: <IconPerson />,
    group: <IconBuilding />,
    cohort: <IconPeople />,
    account: <IconBuilding />,
    ticket: <IconSupport />,
}

export function TodayPeopleRecentRow({
    recent,
    active,
    dataAttr = 'people-sidebar-recent',
}: {
    recent: TodayPeopleRecent
    active: boolean
    dataAttr?: string
}): JSX.Element {
    return (
        <TodayRecentRow
            recent={recent}
            icon={RECENT_TYPE_ICONS[recent.type]}
            typeCopy={todayRecordType(recent.type)}
            active={active}
            dataAttr={dataAttr}
        />
    )
}
