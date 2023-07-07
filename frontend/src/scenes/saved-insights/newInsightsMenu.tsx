import { InsightType } from '~/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { INSIGHT_TYPES_METADATA, InsightTypeMetadata } from 'scenes/saved-insights/SavedInsights'
import { ReactNode } from 'react'
import { insightTypeURL } from 'scenes/insights/utils'

function insightTypesForMenu(): [string, InsightTypeMetadata][] {
    // never show JSON InsightType in the menu
    return Object.entries(INSIGHT_TYPES_METADATA).filter(([insightType]) => insightType !== InsightType.JSON)
}

export function overlayForNewInsightMenu(dataAttr: string): ReactNode[] {
    const menuEntries = insightTypesForMenu()
    return menuEntries.map(
        ([listedInsightType, listedInsightTypeMetadata]) =>
            listedInsightTypeMetadata.inMenu && (
                <LemonButton
                    key={listedInsightType}
                    status="stealth"
                    icon={
                        listedInsightTypeMetadata.icon && (
                            <listedInsightTypeMetadata.icon color="var(--muted-alt)" noBackground />
                        )
                    }
                    to={insightTypeURL[listedInsightType as InsightType]}
                    data-attr={dataAttr}
                    data-attr-insight-type={listedInsightType}
                    onClick={() => {
                        eventUsageLogic.actions.reportSavedInsightNewInsightClicked(listedInsightType)
                    }}
                    fullWidth
                >
                    <div className="text-default flex flex-col text-sm py-1">
                        <strong>{listedInsightTypeMetadata.name}</strong>
                        <span className="text-xs">{listedInsightTypeMetadata.description}</span>
                    </div>
                </LemonButton>
            )
    )
}
