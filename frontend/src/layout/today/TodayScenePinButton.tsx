import { useValues } from 'kea'

import { SidebarPinButton } from './sidebar/SidebarPinButton'
import { recentPane } from './todayRecents'
import { todayRecentsLogic } from './todayRecentsLogic'

export function TodayScenePinButton(): JSX.Element | null {
    const { currentRecent } = useValues(todayRecentsLogic)
    if (!currentRecent) {
        return null
    }
    return (
        <SidebarPinButton
            target={{ type: currentRecent.type, name: currentRecent.name, href: currentRecent.href }}
            size="icon-sm"
            // pinned: `data-attr` values from before the panes shared this button, such as `people-person-title-pin`.
            dataAttr={`${recentPane(currentRecent)}-${currentRecent.type}-title-pin`}
        />
    )
}
