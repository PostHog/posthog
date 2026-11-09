import { useValues } from 'kea'
import { ReactNode } from 'react'

import { PEOPLE_AND_GROUPS_NAV } from '~/layout/panel-layout/navbar/tabs/navProductItems'
import { SceneMainTitleProps, SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { ActivitySceneTabs } from './ActivitySceneTabs'
import { ActivitySceneTabKey } from './activitySceneTabsLogic'

/**
 * The tabs and title of Persons, Cohorts and each group type page. The People pane links to every one of these pages,
 * so there the page shows no tabs. Any other pane under today-rail-nav, like Products, lists them as one product, so
 * the title names that product and the tabs sit below it.
 */
export function PeopleSceneHeader({
    activeKey,
    menuBar,
    ...titleProps
}: SceneMainTitleProps & {
    activeKey: ActivitySceneTabKey
    /** The scene's menu bar. It sits right above the title. */
    menuBar?: ReactNode
}): JSX.Element {
    const { todayRailEnabled, peoplePaneLinksTabs } = useValues(todayShellLogic)

    if (peoplePaneLinksTabs) {
        return (
            <>
                {menuBar}
                <SceneTitleSection {...titleProps} />
            </>
        )
    }

    if (todayRailEnabled) {
        return (
            <>
                {menuBar}
                <SceneTitleSection
                    {...titleProps}
                    name={PEOPLE_AND_GROUPS_NAV.label}
                    resourceType={{ type: PEOPLE_AND_GROUPS_NAV.iconType }}
                />
                <ActivitySceneTabs activeKey={activeKey} />
            </>
        )
    }

    return (
        <>
            <ActivitySceneTabs activeKey={activeKey} className="mb-3" />
            {menuBar}
            <SceneTitleSection {...titleProps} />
        </>
    )
}
