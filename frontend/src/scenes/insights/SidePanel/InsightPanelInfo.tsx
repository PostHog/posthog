import { useActions, useValues } from 'kea'

import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { SceneTags } from 'lib/components/Scenes/SceneTags'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ScenePanelInfoSection } from '~/layout/scenes/SceneLayout'
import { tagsModel } from '~/models/tagsModel'
import { InsightLogicProps } from '~/types'

const RESOURCE_TYPE = 'insight'

export function InsightPanelInfo({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element {
    const theInsightLogic = insightLogic(insightLogicProps)
    const { canEditInsight, insight, isSavingTags } = useValues(theInsightLogic)
    const { setInsightMetadata } = useActions(theInsightLogic)
    const { tags: allExistingTags } = useValues(tagsModel)

    return (
        <ScenePanelInfoSection>
            <SceneTags
                onSave={(tags) => setInsightMetadata({ tags })}
                tags={insight.tags}
                tagsAvailable={allExistingTags}
                dataAttrKey={RESOURCE_TYPE}
                canEdit={canEditInsight}
                loading={isSavingTags}
            />
            <SceneFile dataAttrKey={RESOURCE_TYPE} />
            <SceneActivityIndicator
                at={insight.last_modified_at}
                by={insight.last_modified_by}
                prefix="Last modified"
            />
        </ScenePanelInfoSection>
    )
}
