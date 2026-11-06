import { useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

import { ActivitySceneTabKey, activitySceneTabsLogic, isActivityTabKey } from './activitySceneTabsLogic'

export const ActivitySceneTabs = ({ activeKey }: { activeKey: ActivitySceneTabKey }): JSX.Element | null => {
    const { tabsForKey } = useValues(activitySceneTabsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    // The Today rail's People pane links to Persons, Cohorts and every group type.
    if (todayRailNav && !isActivityTabKey(activeKey)) {
        return null
    }

    return <LemonTabs activeKey={activeKey} tabs={tabsForKey(activeKey)} sceneInset className="mb-3" />
}
