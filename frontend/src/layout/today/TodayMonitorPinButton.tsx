import { useValues } from 'kea'

import { SidebarPinButton } from './sidebar/SidebarPinButton'
import { todayMonitorRecentsLogic } from './todayMonitorRecentsLogic'

/** Shows once the scene reports its loaded issue or saved log view, which happens only with the Monitor pane on. */
export function TodayMonitorPinButton(): JSX.Element | null {
    const { currentRecent } = useValues(todayMonitorRecentsLogic)
    if (!currentRecent) {
        return null
    }
    return (
        <SidebarPinButton
            target={{ type: currentRecent.type, name: currentRecent.name, href: currentRecent.href }}
            size="icon-sm"
            dataAttr={`monitor-${currentRecent.type}-title-pin`}
        />
    )
}
