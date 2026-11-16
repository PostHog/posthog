import { useMemo } from 'react'

import { IconBuilding, IconPeople, IconPerson, IconSupport } from '@posthog/icons'

import { SidebarRow } from '~/layout/today/sidebar/SidebarRow'

import { TodayPeopleRecent, TodayPeopleRecentType, peopleRecentRowKey } from './todayPeople'
import { TodayExplainerPreview } from './todayPreviewCards'
import { TodayPreviewTrigger } from './TodayPreviewTrigger'

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
    // The shared card stores the payload, so it must keep its identity between renders.
    const preview = useMemo<TodayExplainerPreview>(
        () => ({
            kind: 'explainer',
            label: recent.name,
            icon: RECENT_ICONS[recent.type],
            description: RECENT_DESCRIPTIONS[recent.type],
        }),
        [recent.name, recent.type]
    )
    return (
        <TodayPreviewTrigger payload={preview}>
            <SidebarRow
                value={peopleRecentRowKey(recent.href)}
                label={recent.name}
                icon={RECENT_ICONS[recent.type]}
                to={recent.href}
                active={active}
                dataAttr={dataAttr}
            />
        </TodayPreviewTrigger>
    )
}
