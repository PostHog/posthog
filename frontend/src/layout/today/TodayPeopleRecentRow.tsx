import { IconBuilding, IconPeople, IconPerson, IconSupport } from '@posthog/icons'

import { TodayPeopleRecent, TodayPeopleRecentType, peopleRecentRowKey } from './todayPeople'
import { TodayRecentRow } from './TodayRecentRow'

const RECENT_ICONS: Record<TodayPeopleRecentType, JSX.Element> = {
    person: <IconPerson />,
    group: <IconBuilding />,
    cohort: <IconPeople />,
    account: <IconBuilding />,
    ticket: <IconSupport />,
}

const RECENT_DESCRIPTIONS: Record<TodayPeopleRecentType, string> = {
    person: 'A person in your project. Open their page to see their properties, events, and recordings.',
    group: 'A group in your project. Open it to see its properties and activity.',
    cohort: 'A cohort in your project. Open it to see who belongs to it and how it is defined.',
    account: 'A customer account. Open it to see its activity, notes, and related users.',
    ticket: 'A support ticket. Open it to read the conversation and reply.',
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
            value={peopleRecentRowKey(recent.href)}
            name={recent.name}
            href={recent.href}
            icon={RECENT_ICONS[recent.type]}
            description={RECENT_DESCRIPTIONS[recent.type]}
            active={active}
            dataAttr={dataAttr}
        />
    )
}
