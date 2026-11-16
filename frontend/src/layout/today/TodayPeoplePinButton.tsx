import { useValues } from 'kea'

import { SidebarPinButton } from './sidebar/SidebarPinButton'
import { todayPeopleRecentsLogic } from './todayPeopleRecentsLogic'

/** Shows once the scene reports its loaded record, which happens only under the Today layout. */
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
