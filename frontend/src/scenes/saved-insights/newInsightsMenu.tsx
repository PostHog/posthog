import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { INSIGHT_TYPE_URLS } from 'scenes/insights/utils'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'

import { InsightType } from '~/types'

export function OverlayForNewInsightMenu({ dataAttr }: { dataAttr: string }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    const menuEntries = Object.entries(INSIGHT_TYPES_METADATA).filter(
        ([insightType]) =>
            insightType !== InsightType.JSON && (featureFlags[FEATURE_FLAGS.HOG] || insightType !== InsightType.HOG)
    )

    return (
        <>
            {menuEntries.map(
                ([listedInsightType, listedInsightTypeMetadata]) =>
                    listedInsightTypeMetadata.inMenu && (
                        <LemonButton
                            key={listedInsightType}
                            icon={listedInsightTypeMetadata.icon && <listedInsightTypeMetadata.icon />}
                            to={INSIGHT_TYPE_URLS[listedInsightType as InsightType]}
                            data-attr={dataAttr}
                            data-attr-insight-type={listedInsightType}
                            onClick={() => {
                                eventUsageLogic.actions.reportSavedInsightNewInsightClicked(listedInsightType)
                            }}
                            fullWidth
                        >
                            <div className="flex flex-col text-sm py-1">
                                <strong>{listedInsightTypeMetadata.name}</strong>
                                <span className="text-xs font-sans font-normal">
                                    {listedInsightTypeMetadata.description}
                                </span>
                            </div>
                        </LemonButton>
                    )
            )}
        </>
    )
}
