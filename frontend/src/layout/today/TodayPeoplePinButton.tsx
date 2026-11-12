import { useValues } from 'kea'

import { SidebarPinButton } from './sidebar/SidebarPinButton'
import { todayPeopleRecentsLogic } from './todayPeopleRecentsLogic'

/**
 * The pin after the name of an open person, group, cohort, account or ticket. It reads the record the scene reports,
 * so it shows only once the record has loaded, and only under the Today layout.
 */
export function TodayPeoplePinButton(): JSX.Element | null {
    const { currentRecent } = useValues(todayPeopleRecentsLogic)
    if (!currentRecent) {
        return null
    }
    return (
        <SidebarPinButton
            target={{ type: currentRecent.type, name: currentRecent.name, href: currentRecent.href }}
            size="icon-sm"
            dataAttr={`people-${currentRecent.type}-title-pin`}
        />
    )
}
