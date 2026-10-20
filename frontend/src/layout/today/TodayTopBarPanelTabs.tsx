import { useValues } from 'kea'

import { todayContextPanelLogic } from './todayContextPanelLogic'
import { TodayTopBarPanelTab } from './TodayTopBarPanelTab'

export function TodayTopBarPanelTabs(): JSX.Element {
    const { panelTabs } = useValues(todayContextPanelLogic)

    return (
        <div className="flex items-center gap-0.5">
            {panelTabs.map((tab) => (
                <TodayTopBarPanelTab key={tab} tab={tab} />
            ))}
        </div>
    )
}
