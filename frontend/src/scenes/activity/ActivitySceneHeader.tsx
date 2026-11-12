import { useValues } from 'kea'
import { ReactNode } from 'react'

import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { todayShellLogic } from '~/layout/today/todayShellLogic'
import { FileSystemIconType } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

import { ActivitySceneTabs } from './ActivitySceneTabs'

const ACTIVITY_SCENE = sceneConfigurations[Scene.Activity]

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
    if (!todayRailEnabled) {
        return (
            <>
                <ActivitySceneTabs activeKey={activeKey} className="mb-3" />
                {banner}
                <SceneTitleSection
                    name={name}
                    description={description}
                    resourceType={{ type: iconType || 'default_icon_type' }}
                />
            </>
        )
    }

    // The tabs below name the open view, so every tab shares the Activity title.
    return (
        <>
            <SceneTitleSection
                name={ACTIVITY_SCENE.name}
                description={description}
                resourceType={{ type: ACTIVITY_SCENE.iconType || 'default_icon_type' }}
            />
            <ActivitySceneTabs activeKey={activeKey} className="mb-3" />
            {banner}
        </>
    )
}
