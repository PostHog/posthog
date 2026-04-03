import { ScenePanel, ScenePanelDivider } from '~/layout/scenes/SceneLayout'
import { InsightLogicProps } from '~/types'

import { InsightPanelActions } from './InsightPanelActions'
import { InsightPanelDangerZone } from './InsightPanelDangerZone'
import { InsightPanelInfo } from './InsightPanelInfo'
import { InsightPanelToggles } from './InsightPanelToggles'

export function InsightSidePanelContent({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element {
    return (
        <ScenePanel>
            <InsightPanelInfo insightLogicProps={insightLogicProps} />
            <ScenePanelDivider />
            <InsightPanelActions insightLogicProps={insightLogicProps} />
            <ScenePanelDivider />
            <InsightPanelToggles insightLogicProps={insightLogicProps} />
            <InsightPanelDangerZone insightLogicProps={insightLogicProps} />
        </ScenePanel>
    )
}
