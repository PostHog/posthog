import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { ReactNode } from 'react'
import { insightTypeURL } from 'scenes/insights/utils'
import { INSIGHT_TYPES_METADATA, InsightTypeMetadata } from 'scenes/saved-insights/SavedInsights'

import { InsightType } from '~/types'

function insightTypesForMenu(): [string, InsightTypeMetadata][] {
    // never show JSON InsightType in the menu
    return Object.entries(INSIGHT_TYPES_METADATA).filter(([insightType]) => insightType !== InsightType.JSON)
}

export function overlayForNewInsightMenu(dataAttr: string): ReactNode[] {
    const menuEntries = insightTypesForMenu()

    const insightTypeUrls = insightTypeURL(
        Boolean(featureFlagLogic.findMounted()?.values.featureFlags?.[FEATURE_FLAGS.BI_VIZ])
    )

    return menuEntries.map(
        ([listedInsightType, listedInsightTypeMetadata]) =>
            listedInsightTypeMetadata.inMenu && (
                <LemonButton
                    key={listedInsightType}
                    icon={
                        listedInsightTypeMetadata.icon && (
                            <listedInsightTypeMetadata.icon color="var(--muted-alt)" noBackground />
                        )
                    }
                    to={insightTypeUrls[listedInsightType as InsightType]}
                    data-attr={dataAttr}
                    data-attr-insight-type={listedInsightType}
                    onClick={() => {
                        eventUsageLogic.actions.reportSavedInsightNewInsightClicked(listedInsightType)
                    }}
                    fullWidth
                >
                    <div className="text-default flex flex-col text-sm py-1">
                        <strong>{listedInsightTypeMetadata.name}</strong>
                        <span className="text-xs font-sans">{listedInsightTypeMetadata.description}</span>
                    </div>
                </LemonButton>
            )
    )
}
