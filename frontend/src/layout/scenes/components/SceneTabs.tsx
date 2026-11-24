import { useValues } from 'kea'

import { LemonTabs, LemonTabsProps } from 'lib/lemon-ui/LemonTabs'

import { todayShellLogic } from '~/layout/today/todayShellLogic'

export interface SceneTabsProps<T extends string | number> extends LemonTabsProps<T> {
    /** The warehouse sidebar lists these tabs as its own items, so under the rail navigation the bar is not drawn at all. */
    listedInWarehouseMenu?: boolean
}

/** A drop-in for `LemonTabs` that hides its bar when the warehouse sidebar already lists the tabs. */
export function SceneTabs<T extends string | number>({
    listedInWarehouseMenu = false,
    ...props
}: SceneTabsProps<T>): JSX.Element {
    const { todayRailEnabled, routePane } = useValues(todayShellLogic)
    const inWarehouseMenu = listedInWarehouseMenu && todayRailEnabled && routePane === 'warehouse'

    return <LemonTabs {...props} barHidden={inWarehouseMenu || props.barHidden} />
}
