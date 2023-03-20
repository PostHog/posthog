import { InsightType } from '~/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { INSIGHT_TYPES_METADATA, InsightTypeMetadata } from 'scenes/saved-insights/SavedInsights'
import { ReactNode } from 'react'
import { urls } from 'scenes/urls'
import { examples } from '~/queries/examples'

const insightTypeURL: Record<InsightType, string> = {
    TRENDS: urls.insightNew({ insight: InsightType.TRENDS }),
    STICKINESS: urls.insightNew({ insight: InsightType.STICKINESS }),
    LIFECYCLE: urls.insightNew({ insight: InsightType.LIFECYCLE }),
    FUNNELS: urls.insightNew({ insight: InsightType.FUNNELS }),
    RETENTION: urls.insightNew({ insight: InsightType.RETENTION }),
    PATHS: urls.insightNew({ insight: InsightType.PATHS }),
    SQL: urls.insightNew(undefined, undefined, JSON.stringify(examples.HogQLTable)),
    JSON: urls.insightNew(undefined, undefined, JSON.stringify(examples.EventsTableFull)),
}

function insightTypesForMenu(isUsingDataExplorationQueryTab: boolean): [string, InsightTypeMetadata][] {
    let menuEntries = Object.entries(INSIGHT_TYPES_METADATA)
    if (!isUsingDataExplorationQueryTab) {
        menuEntries = menuEntries.filter(
            ([insightType]) => insightType !== InsightType.JSON && insightType !== InsightType.SQL
        )
    }
    return menuEntries
}

export function overlayForNewInsightMenu(
    dataAttr: string,
    isUsingDatExplorationQuery: boolean,
    clickHandler?: () => void
): ReactNode[] {
    const menuEntries = insightTypesForMenu(isUsingDatExplorationQuery)
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
                        clickHandler?.()
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
