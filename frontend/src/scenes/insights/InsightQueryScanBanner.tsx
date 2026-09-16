import { useActions, useValues } from 'kea'

import { autoRunMaxPrompt } from 'scenes/max/maxPrompt'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { QueryScanBanner } from '~/queries/nodes/DataNode/QueryScanBanner'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import { InsightLogicProps, SidePanelTab } from '~/types'

export function InsightQueryScanBanner({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element {
    const { queryScan } = useValues(dataNodeLogic({ key: insightVizDataNodeKey(insightProps) } as DataNodeLogicProps))
    const { openSidePanel } = useActions(sidePanelStateLogic)

    const askAssistant = (): void => {
        if (!queryScan?.assistantPrompt) {
            return
        }
        openSidePanel(SidePanelTab.Max, autoRunMaxPrompt(queryScan.assistantPrompt))
    }

    return <QueryScanBanner queryScan={queryScan} onFixWithAI={askAssistant} />
}
