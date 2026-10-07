import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { createPortal } from 'react-dom'

import { LemonTab, LemonTabs, LemonTabsProps } from 'lib/lemon-ui/LemonTabs'

import { TodaySceneTabsList } from '~/layout/today/TodaySceneTabsList'
import { todaySceneTabsLogic } from '~/layout/today/todaySceneTabsLogic'
import { todayShellLogic } from '~/layout/today/todayShellLogic'

/** A drop-in for `LemonTabs` whose bar moves to the warehouse sidebar under the rail navigation. */
export function SceneTabs<T extends string | number>(props: LemonTabsProps<T>): JSX.Element {
    const { todayRailEnabled, routePane, sceneTabsInSidebar } = useValues(todayShellLogic)
    const { tabsElement } = useValues(todaySceneTabsLogic)
    const { addSceneTabs, removeSceneTabs } = useActions(todaySceneTabsLogic)

    const inWarehouse = todayRailEnabled && routePane === 'warehouse'
    useEffect(() => {
        if (inWarehouse) {
            addSceneTabs()
            return () => removeSceneTabs()
        }
    }, [inWarehouse]) // oxlint-disable-line react-hooks/exhaustive-deps

    if (!sceneTabsInSidebar) {
        return <LemonTabs {...props} />
    }

    const realTabs = props.tabs.filter(Boolean) as LemonTab<T>[]
    return (
        <>
            {tabsElement &&
                createPortal(
                    <TodaySceneTabsList
                        tabs={realTabs}
                        activeKey={props.activeKey}
                        onChange={props.onChange}
                        dataAttr={props['data-attr']}
                    />,
                    tabsElement
                )}
            <LemonTabs {...props} barHidden />
        </>
    )
}
