import { useActions, useValues } from 'kea'

import { autoRunMaxPrompt } from 'scenes/max/maxPrompt'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { QueryScanBanner } from '~/queries/nodes/DataNode/QueryScanBanner'
import { SidePanelTab } from '~/types'

export function EditorQueryScanBanner(): JSX.Element | null {
    const { queryScan } = useValues(dataNodeLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)

    // The editor registers the `execute_sql` tool with the current query, so the assistant reads the
    // query from there and writes its proposal back through the same tool.
    const askAssistant = (): void => {
        if (!queryScan?.assistantPrompt) {
            return
        }
        openSidePanel(SidePanelTab.Max, autoRunMaxPrompt(queryScan.assistantPrompt))
    }

    return <QueryScanBanner className="m-2" queryScan={queryScan} onFixWithAI={askAssistant} />
}
