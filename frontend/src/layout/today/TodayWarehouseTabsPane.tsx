import { useActions } from 'kea'

import { todaySceneTabsLogic } from './todaySceneTabsLogic'

/** The warehouse pane's body. Pages portal their scene tabs into it. */
export function TodayWarehouseTabsPane(): JSX.Element {
    const { registerTabsElement } = useActions(todaySceneTabsLogic)
    return <div className="TodayPane" data-quill ref={registerTabsElement} />
}
