import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { uuid } from 'lib/utils'
import { MaxInstance } from 'scenes/max/Max'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

export function SidePanelMax(): JSX.Element | null {
    const { sidePanelTabId } = useValues(maxGlobalLogic)
    const { registerTab, setSidePanelTab } = useActions(maxGlobalLogic)
    useEffect(() => {
        if (!sidePanelTabId) {
            const newTabId = uuid()
            registerTab(newTabId)
            setSidePanelTab(newTabId)
        }
    }, [sidePanelTabId])
    return sidePanelTabId ? <MaxInstance sidePanel tabId={sidePanelTabId} /> : null
}
