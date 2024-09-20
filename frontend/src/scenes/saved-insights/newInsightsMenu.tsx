import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { ReactNode } from 'react'
import { insightTypeURL } from 'scenes/insights/utils'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'

import { InsightType } from '~/types'

export function overlayForNewInsightMenu(dataAttr: string): ReactNode[] {
    const menuEntries = Object.entries(INSIGHT_TYPES_METADATA).filter(
        ([insightType]) => insightType !== InsightType.JSON
    )

    return menuEntries.map(
        ([listedInsightType, listedInsightTypeMetadata]) =>
            listedInsightTypeMetadata.inMenu && (
                <LemonButton
                    key={listedInsightType}
                    icon={listedInsightTypeMetadata.icon && <listedInsightTypeMetadata.icon />}
                    to={insightTypeURL[listedInsightType as InsightType]}
                    data-attr={dataAttr}
                    data-attr-insight-type={listedInsightType}
                    onClick={() => {
                        eventUsageLogic.actions.reportSavedInsightNewInsightClicked(listedInsightType)
                    }}
                    fullWidth
                >
                    <div className="flex flex-col text-sm py-1">
                        <strong>{listedInsightTypeMetadata.name}</strong>
                        <span className="text-xs font-sans font-normal">{listedInsightTypeMetadata.description}</span>
                    </div>
                </LemonButton>
            )
    )
}
