import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { createPortal } from 'react-dom'

import { LemonTab, LemonTabs, LemonTabsProps } from 'lib/lemon-ui/LemonTabs'

import { TodaySceneTabsList } from '~/layout/today/TodaySceneTabsList'
import { todaySceneTabsLogic } from '~/layout/today/todaySceneTabsLogic'
import { todayShellLogic } from '~/layout/today/todayShellLogic'

export interface SceneTabsProps<T extends string | number> extends LemonTabsProps<T> {
    /** The warehouse menu lists these tabs as its own items, so under the rail navigation the bar is not drawn at all. */
    listedInWarehouseMenu?: boolean
}

/** A drop-in for `LemonTabs` whose bar moves to the warehouse sidebar under the rail navigation. */
export function SceneTabs<T extends string | number>({
    listedInWarehouseMenu = false,
    ...props
}: SceneTabsProps<T>): JSX.Element {
    const { todayRailEnabled, routePane, sceneTabsInSidebar } = useValues(todayShellLogic)
    const { tabsElement } = useValues(todaySceneTabsLogic)
    const { addSceneTabs, removeSceneTabs } = useActions(todaySceneTabsLogic)

    const inWarehouse = todayRailEnabled && routePane === 'warehouse'
    const inWarehouseMenu = inWarehouse && listedInWarehouseMenu
    useEffect(() => {
        if (inWarehouse && !inWarehouseMenu) {
            addSceneTabs()
            return () => removeSceneTabs()
        }
    }, [inWarehouse, inWarehouseMenu]) // oxlint-disable-line react-hooks/exhaustive-deps

    // LemonTabs keeps the same position whether or not the bar is in the sidebar, so toggling the sidebar keeps the
    // tab content mounted, with its state.
    return (
        <>
            {sceneTabsInSidebar &&
                !inWarehouseMenu &&
                tabsElement &&
                createPortal(
                    <TodaySceneTabsList
                        tabs={props.tabs.filter(Boolean) as LemonTab<T>[]}
                        activeKey={props.activeKey}
                        onChange={props.onChange}
                        dataAttr={props['data-attr']}
                    />,
                    tabsElement
                )}
            <LemonTabs {...props} barHidden={sceneTabsInSidebar || inWarehouseMenu || props.barHidden} />
        </>
    )
}
