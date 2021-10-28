import React from 'react'
import { AvailableFeature, DashboardItemType, ItemMode } from '~/types'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { ObjectTags } from 'lib/components/ObjectTags'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'
import { FEATURE_FLAGS } from 'lib/constants'

function createInsightInputClassName(type: string): string {
    return `insight-metadata-input insight-metadata-${type}`
}

interface MetadataProps {
    insight: Partial<DashboardItemType>
    insightMode: ItemMode
}

function Tags({ insight }: MetadataProps): JSX.Element | null {
    const { saveNewTag, deleteTag } = useActions(insightLogic)
    const { tagLoading } = useValues(insightLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { user } = useValues(userLogic)
    // TODO: this needs to be put back in insightMetadataLogic, but after out-of-scope refactors
    const isEditable = !!(
        featureFlags[FEATURE_FLAGS.SAVED_INSIGHTS] &&
        user?.organization?.available_features?.includes(AvailableFeature.DASHBOARD_COLLABORATION)
    )

    if (!isEditable) {
        return null
    }

    return (
        <div className={createInsightInputClassName('tags')} data-attr="insight-tags">
            <ObjectTags
                tags={insight.tags ?? []}
                onTagSave={saveNewTag}
                onTagDelete={deleteTag}
                saving={tagLoading}
                tagsAvailable={[]}
            />
        </div>
    )
}

export const InsightMetadata = {
    Tags,
}
