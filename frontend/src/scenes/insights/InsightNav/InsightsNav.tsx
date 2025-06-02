import { useActions, useValues } from 'kea'
import { AlertDeletionWarning } from 'lib/components/Alerts/AlertDeletionWarning'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightNavLogic } from 'scenes/insights/InsightNav/insightNavLogic'
import { INSIGHT_TYPE_URLS } from 'scenes/insights/utils'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'

import { InsightType } from '~/types'

import { insightLogic } from '../insightLogic'
import { FunnelsCue } from '../views/Trends/FunnelsCue'

export function InsightsNav(): JSX.Element {
    const { insightProps, insight } = useValues(insightLogic)
    const { activeView, tabs } = useValues(insightNavLogic(insightProps))
    const { setActiveView } = useActions(insightNavLogic(insightProps))

    const { featureFlags } = useValues(featureFlagLogic)
    const calendarHeatmapInsightEnabled = featureFlags[FEATURE_FLAGS.CALENDAR_HEATMAP_INSIGHT]
    const filteredTabs = calendarHeatmapInsightEnabled
        ? tabs
        : tabs.filter((tab) => tab.type !== InsightType.CALENDAR_HEATMAP)

    return (
        <>
            <FunnelsCue />
            {insight.short_id && <AlertDeletionWarning />}
            <LemonTabs
                activeKey={activeView}
                onChange={(newKey) => setActiveView(newKey)}
                tabs={filteredTabs.map(({ label, type, dataAttr }) => ({
                    key: type,
                    label: (
                        <Link to={INSIGHT_TYPE_URLS[type]} preventClick data-attr={dataAttr}>
                            <Tooltip
                                placement="top"
                                title={
                                    INSIGHT_TYPES_METADATA[type].tooltipDescription ||
                                    INSIGHT_TYPES_METADATA[type].description
                                }
                                docLink={INSIGHT_TYPES_METADATA[type].tooltipDocLink}
                            >
                                <span>{label}</span>
                            </Tooltip>
                        </Link>
                    ),
                }))}
            />
        </>
    )
}
