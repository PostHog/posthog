import { useValues } from 'kea'
import { ReactNode } from 'react'

import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { todayShellLogic } from '~/layout/today/todayShellLogic'
import { FileSystemIconType } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

import { ActivitySceneTabs } from './ActivitySceneTabs'
import { activitySceneTabsLogic } from './activitySceneTabsLogic'

const ACTIVITY_BREADCRUMB = {
    key: Scene.Activity,
    name: sceneConfigurations[Scene.Activity].name,
    path: urls.activity(),
}

export function ActivitySceneHeader({
    activeKey,
    name,
    description,
    iconType,
    banner,
}: {
    activeKey: ActivityTab
    name: string | undefined
    description?: string
    iconType: FileSystemIconType | undefined
    /** A notice for the scene. It sits between the tabs and the title, or below the tabs under the Today layout. */
    banner?: ReactNode
}): JSX.Element {
    const { todayRailEnabled } = useValues(todayShellLogic)
    const { activityTabs } = useValues(activitySceneTabsLogic)
    const resourceType = { type: iconType || 'default_icon_type' }

    if (!todayRailEnabled) {
        return (
            <>
                <ActivitySceneTabs activeKey={activeKey} />
                {banner}
                <SceneTitleSection name={name} description={description} resourceType={resourceType} />
            </>
        )
    }

    const tabLabel = activityTabs.find((tab) => tab.key === activeKey)?.label ?? name
    return (
        <>
            <SceneTitleSection
                name={tabLabel}
                description={description}
                resourceType={resourceType}
                forceBackTo={ACTIVITY_BREADCRUMB}
            />
            <ActivitySceneTabs activeKey={activeKey} />
            {banner}
        </>
    )
}
