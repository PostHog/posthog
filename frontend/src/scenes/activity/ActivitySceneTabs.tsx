import { useValues } from 'kea'

import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

import { ActivitySceneTabKey, activitySceneTabsLogic } from './activitySceneTabsLogic'

export const ActivitySceneTabs = ({
    activeKey,
    className,
}: {
    activeKey: ActivitySceneTabKey
    className?: string
}): JSX.Element => {
    const { tabsForKey } = useValues(activitySceneTabsLogic)

    return <LemonTabs activeKey={activeKey} tabs={tabsForKey(activeKey)} sceneInset className={className} />
}
