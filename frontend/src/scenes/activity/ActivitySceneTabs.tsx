import { useValues } from 'kea'

import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

import { ActivitySceneTabKey, activitySceneTabsLogic } from './activitySceneTabsLogic'

export const ActivitySceneTabs = ({ activeKey }: { activeKey: ActivitySceneTabKey }): JSX.Element => {
    const { tabsForKey } = useValues(activitySceneTabsLogic)

    return <LemonTabs activeKey={activeKey} tabs={tabsForKey(activeKey)} sceneInset className="mb-3" />
}
