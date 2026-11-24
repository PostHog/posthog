import { IconBuilding, IconPeople, IconPerson, IconSupport } from '@posthog/icons'

import { TodayPeopleRecent, TodayPeopleRecentType } from './todayPeople'
import { TodayRecentRow } from './TodayRecentRow'
import { TodayRecentTypeCopy } from './todayRecents'

const RECENT_TYPE_INFO: Record<TodayPeopleRecentType, TodayRecentTypeCopy & { icon: JSX.Element }> = {
    person: {
        icon: <IconPerson />,
        label: 'Person',
        description: 'A person in your project. Open their page to see their properties, events, and recordings.',
    },
    group: {
        icon: <IconBuilding />,
        label: 'Group',
        description: 'A group in your project. Open it to see its properties and activity.',
    },
    cohort: {
        icon: <IconPeople />,
        label: 'Cohort',
        description: 'A cohort in your project. Open it to see who belongs to it and how it is defined.',
    },
    account: {
        icon: <IconBuilding />,
        label: 'Account',
        description: 'A customer account. Open it to see its activity, notes, and related users.',
    },
    ticket: {
        icon: <IconSupport />,
        label: 'Ticket',
        description: 'A support ticket. Open it to read the conversation and reply.',
    },
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
    const typeInfo = RECENT_TYPE_INFO[recent.type]
    return (
        <TodayRecentRow recent={recent} icon={typeInfo.icon} typeCopy={typeInfo} active={active} dataAttr={dataAttr} />
    )
}
